#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <libkern/OSByteOrder.h>
#include <stdbool.h>
#include <time.h>

static int64_t number_property(io_service_t service, CFStringRef key) {
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key, NULL, 0);
    int64_t number = -1;
    if (value) {
        if (CFGetTypeID(value) == CFNumberGetTypeID()) {
            if (!CFNumberGetValue(value, kCFNumberSInt64Type, &number))
                number = -1;
        }
        CFRelease(value);
    }
    return number;
}

static PyObject *io_error(const char *operation, int32_t status) {
    return PyErr_Format(PyExc_OSError, "%s failed (0x%08x)", operation, (unsigned int)status);
}

typedef IOUSBDeviceInterface **USBDevice;

static USBDevice device_interface(io_service_t service, IOCFPlugInInterface ***plugin) {
    SInt32 score;
    IOReturn status = IOCreatePlugInInterfaceForService(
        service, kIOUSBDeviceUserClientTypeID, kIOCFPlugInInterfaceID, plugin, &score);
    if (status != kIOReturnSuccess) {
        io_error("Creating USB device plug-in", status);
        return NULL;
    }
    USBDevice device = NULL;
    HRESULT query = (**plugin)->QueryInterface(
        *plugin, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID100), (LPVOID *)&device);
    if (query != S_OK || !device) {
        IODestroyPlugInInterface(*plugin);
        io_error("Querying USB device interface", query);
        return NULL;
    }
    return device;
}

static IOUSBConfigurationDescriptorPtr configuration_at(USBDevice device, UInt8 index) {
    IOUSBConfigurationDescriptorPtr descriptor = NULL;
    IOReturn status = (*device)->GetConfigurationDescriptorPtr(device, index, &descriptor);
    if (status != kIOReturnSuccess) {
        io_error("Getting configuration descriptor", status);
        return NULL;
    }
    if (!descriptor || descriptor->bLength < 9 || descriptor->bDescriptorType != 2 ||
        OSSwapLittleToHostInt16(descriptor->wTotalLength) < descriptor->bLength) {
        PyErr_SetString(PyExc_ValueError, "invalid configuration descriptor header");
        return NULL;
    }
    return descriptor;
}

static PyObject *configurations(io_service_t service) {
    IOCFPlugInInterface **plugin = NULL;
    USBDevice device = device_interface(service, &plugin);
    if (!device)
        return NULL;
    UInt8 count = 0;
    PyObject *result = NULL;
    IOReturn status = (*device)->GetNumberOfConfigurations(device, &count);
    if (status != kIOReturnSuccess) {
        io_error("Getting configuration count", status);
        goto done;
    }
    if (!count) {
        PyErr_SetString(PyExc_ValueError, "device advertises zero configurations");
        goto done;
    }
    result = PyList_New(count);
    if (!result)
        goto done;
    for (int index = 0; index < count; index++) {
        IOUSBConfigurationDescriptorPtr descriptor = configuration_at(device, index);
        if (!descriptor) {
            Py_CLEAR(result);
            break;
        }
        // The SDK owns this buffer and specifies its extent in USB bus byte order.
        PyObject *data = PyBytes_FromStringAndSize(
            (const char *)descriptor, OSSwapLittleToHostInt16(descriptor->wTotalLength));
        if (!data) {
            Py_CLEAR(result);
            break;
        }
        PyList_SET_ITEM(result, index, data);
    }
done:
    (*device)->Release(device);
    IODestroyPlugInInterface(plugin);
    return result;
}

static bool is_dice(io_service_t service) {
    return number_property(service, CFSTR(kUSBVendorID)) == 0x17aa &&
           number_property(service, CFSTR(kUSBProductID)) == 0xd1ce;
}

static int append_device(PyObject *devices, io_service_t service) {
    if (!is_dice(service))
        return 0;

    int64_t usb = number_property(service, CFSTR(kUSBStandardVersion));
    int64_t release = number_property(service, CFSTR(kUSBDeviceReleaseNumber));
    if (usb < 0 || usb > UINT16_MAX || release < 0 || release > UINT16_MAX) {
        PyErr_SetString(PyExc_OSError, "USB revision properties unavailable");
        return -1;
    }
    int64_t location = number_property(service, CFSTR(kUSBHostPropertyLocationID));
    int64_t address = number_property(service, CFSTR(kUSBHostDevicePropertyAddress));
    int bus = location != -1 && location != 0 && location >= INT32_MIN && location <= UINT32_MAX
              ? (int)((uint32_t)location >> 24) : -1;
    PyObject *configs = configurations(service);
    if (!configs)
        return -1;
    PyObject *row = Py_BuildValue("(iiiiiiN)", 0x17aa, 0xd1ce, (int)usb,
                                  (int)release, bus, address >= 0 && address <= 127 ? (int)address : -1,
                                  configs);
    if (!row)
        return -1;
    int status = PyList_Append(devices, row);
    Py_DECREF(row);
    return status;
}

static io_iterator_t device_iterator(void) {
    CFMutableDictionaryRef match = IOServiceMatching(kIOUSBHostDeviceClassName);
    if (!match) {
        PyErr_NoMemory();
        return IO_OBJECT_NULL;
    }
    io_iterator_t iter = IO_OBJECT_NULL;
    IOReturn status = IOServiceGetMatchingServices(kIOMainPortDefault, match, &iter);
    if (status != kIOReturnSuccess) {
        io_error("Matching USB devices", status);
        return IO_OBJECT_NULL;
    }
    return iter;
}

static PyObject *devices(PyObject *self, PyObject *args) {
    io_iterator_t iter = device_iterator();
    // IOKit can report a successful empty match with a null iterator.
    if (!iter)
        return PyErr_Occurred() ? NULL : PyList_New(0);

    PyObject *result = PyList_New(0);
    if (result) {
        io_service_t service;
        while ((service = IOIteratorNext(iter)) != IO_OBJECT_NULL) {
            int appended = append_device(result, service);
            IOObjectRelease(service);
            if (appended < 0) {
                Py_CLEAR(result);
                break;
            }
        }
        if (result && !IOIteratorIsValid(iter)) {
            PyErr_SetString(PyExc_OSError, "USB device list changed during inventory");
            Py_CLEAR(result);
        }
    }
    IOObjectRelease(iter);
    return result;
}

static io_service_t unique_match(io_iterator_t iter, bool (*match)(io_service_t), const char *name) {
    io_service_t selected = IO_OBJECT_NULL;
    io_service_t service;
    while ((service = IOIteratorNext(iter)) != IO_OBJECT_NULL) {
        if (!match(service)) {
            IOObjectRelease(service);
            continue;
        }
        if (selected) {
            IOObjectRelease(service);
            IOObjectRelease(selected);
            selected = IO_OBJECT_NULL;
            PyErr_Format(PyExc_OSError, "Multiple matching %s", name);
            break;
        }
        selected = service;
    }
    if (!IOIteratorIsValid(iter)) {
        if (selected)
            IOObjectRelease(selected);
        selected = IO_OBJECT_NULL;
        PyErr_Format(PyExc_OSError, "%s list changed during discovery", name);
    } else if (!selected && !PyErr_Occurred()) {
        PyErr_Format(PyExc_OSError, "No matching %s", name);
    }
    IOObjectRelease(iter);
    return selected;
}

static bool is_interface_zero(io_service_t service) {
    return IOObjectConformsTo(service, kIOUSBHostInterfaceClassName) &&
           number_property(service, CFSTR(kUSBInterfaceNumber)) == 0;
}

static bool select_rfc_configuration(USBDevice device) {
    UInt8 count;
    IOReturn status = (*device)->GetNumberOfConfigurations(device, &count);
    if (status != kIOReturnSuccess) {
        io_error("Getting configuration count", status);
        return false;
    }
    for (int index = 0; index < count; index++) {
        IOUSBConfigurationDescriptorPtr descriptor = configuration_at(device, index);
        if (!descriptor)
            return false;
        if (descriptor->bConfigurationValue == 1) {
            status = (*device)->SetConfiguration(device, 1);
            if (status == kIOReturnSuccess)
                return true;
            io_error("Selecting DiCE configuration 1", status);
            return false;
        }
    }
    PyErr_SetString(PyExc_OSError, "DiCE does not advertise USB configuration 1");
    return false;
}

static bool ensure_rfc_configuration(USBDevice device) {
    UInt8 active;
    IOReturn status = (*device)->GetConfiguration(device, &active);
    if (status != kIOReturnSuccess) {
        io_error("Reading active USB configuration", status);
        return false;
    }
    if (active == 0) {
        status = (*device)->USBDeviceOpen(device);
        if (status != kIOReturnSuccess) {
            io_error("Opening DiCE USB device without seizing it", status);
            return false;
        }
        // Another owner may have configured the adapter between the read and the open.
        status = (*device)->GetConfiguration(device, &active);
        if (status != kIOReturnSuccess)
            io_error("Rechecking active USB configuration", status);
        else if (active == 0 && select_rfc_configuration(device))
            active = 1;
        status = (*device)->USBDeviceClose(device);
        if (status != kIOReturnSuccess && !PyErr_Occurred())
            io_error("Closing DiCE USB device", status);
        if (PyErr_Occurred())
            return false;
    }
    if (active != 1) {
        PyErr_Format(PyExc_OSError, "Unexpected active DiCE configuration %u", (unsigned)active);
        return false;
    }
    return true;
}

static io_iterator_t active_interfaces(USBDevice device) {
    if (!ensure_rfc_configuration(device))
        return IO_OBJECT_NULL;
    IOUSBFindInterfaceRequest request = {
        kIOUSBFindInterfaceDontCare, kIOUSBFindInterfaceDontCare, kIOUSBFindInterfaceDontCare, 0
    };
    io_iterator_t iter = IO_OBJECT_NULL;
    IOReturn status = (*device)->CreateInterfaceIterator(device, &request, &iter);
    if (status != kIOReturnSuccess) {
        io_error("Enumerating active USB interfaces", status);
        return IO_OBJECT_NULL;
    }
    if (!iter)
        PyErr_SetString(PyExc_OSError, "No matching active DiCE interface 0");
    return iter;
}

static io_service_t rfc_interface(void) {
    io_iterator_t devices = device_iterator();
    if (!devices) {
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_OSError, "No matching DiCE USB device (17aa:d1ce)");
        return IO_OBJECT_NULL;
    }
    io_service_t device = unique_match(devices, is_dice, "DiCE USB device (17aa:d1ce)");
    if (!device)
        return IO_OBJECT_NULL;
    IOCFPlugInInterface **plugin = NULL;
    USBDevice usb = device_interface(device, &plugin);
    IOObjectRelease(device);
    if (!usb)
        return IO_OBJECT_NULL;
    io_iterator_t interfaces = active_interfaces(usb);
    (*usb)->Release(usb);
    IODestroyPlugInInterface(plugin);
    return interfaces ? unique_match(interfaces, is_interface_zero, "active DiCE interface 0") : IO_OBJECT_NULL;
}

typedef IOUSBInterfaceInterface182 **USBInterface;

static bool check_interface(USBInterface usb) {
    UInt8 config, number, alternate, endpoints;
    IOReturn status = (*usb)->GetConfigurationValue(usb, &config);
    if (status == kIOReturnSuccess)
        status = (*usb)->GetInterfaceNumber(usb, &number);
    if (status == kIOReturnSuccess)
        status = (*usb)->GetAlternateSetting(usb, &alternate);
    if (status == kIOReturnSuccess)
        status = (*usb)->GetNumEndpoints(usb, &endpoints);
    if (status != kIOReturnSuccess) {
        io_error("Inspecting active interface", status);
        return false;
    }
    if (config != 1 || number != 0 || alternate != 0 || endpoints != 2) {
        PyErr_SetString(PyExc_OSError, "Expected configuration 1, interface 0, alternate 0, two pipes");
        return false;
    }
    return true;
}

static bool find_rfc_pipes(USBInterface usb, UInt8 *input, UInt8 *output) {
    for (UInt8 pipe = 1; pipe <= 2; pipe++) {
        UInt8 direction, number, type, interval;
        UInt16 packet;
        IOReturn status = (*usb)->GetPipeProperties(
            usb, pipe, &direction, &number, &type, &packet, &interval);
        if (status != kIOReturnSuccess) {
            io_error("Inspecting active pipe", status);
            return false;
        }
        if (number == 1 && type == kUSBBulk && packet == 512) {
            if (direction == kUSBIn)
                *input = pipe;
            if (direction == kUSBOut)
                *output = pipe;
        }
    }
    if (!*input || !*output) {
        PyErr_SetString(PyExc_OSError, "Expected bulk IN 0x81 and OUT 0x01 with 512-byte packets");
        return false;
    }
    return true;
}

static PyObject *exchange_rfc_version(USBInterface usb, UInt8 input, UInt8 output) {
    UInt8 request[] = {0xb5, 0x02, 0x00, 0x20, 0x00, 0x69};
    IOReturn status = (*usb)->WritePipeTO(usb, output, request, sizeof(request), 1000, 1000);
    if (status != kIOReturnSuccess)
        return io_error("RFC version OUT transfer", status);

    const uint64_t ms = 1000000;
    uint64_t deadline = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) + 2000 * ms;
    UInt8 reply[10];
    size_t used = 0;
    for (int reads = 0; reads < 16 && used < sizeof(reply); reads++) {
        uint64_t now = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
        if (now >= deadline)
            return PyErr_Format(PyExc_TimeoutError, "RFC version IN deadline after %zu bytes", used);
        UInt32 timeout = (UInt32)((deadline - now + ms - 1) / ms);
        UInt8 packet[512];
        UInt32 size = sizeof(packet);
        status = (*usb)->ReadPipeTO(usb, input, packet, &size, timeout, timeout);
        if (status != kIOReturnSuccess)
            return io_error("RFC version IN transfer", status);
        if (clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) > deadline)
            return PyErr_Format(PyExc_TimeoutError, "RFC version IN exceeded its deadline");
        if (size > sizeof(reply) - used)
            return PyErr_Format(PyExc_ValueError, "unexpected trailing bytes in RFC version reply");
        memcpy(reply + used, packet, size);
        used += size;
    }
    return PyBytes_FromStringAndSize((const char *)reply, (Py_ssize_t)used);
}

static PyObject *read_from_interface(USBInterface usb) {
    if (!check_interface(usb))
        return NULL;
    IOReturn status = (*usb)->USBInterfaceOpen(usb);
    if (status != kIOReturnSuccess)
        return io_error("Opening DiCE interface without seizing it", status);
    UInt8 input = 0, output = 0;
    PyObject *reply = NULL;
    if (check_interface(usb) && find_rfc_pipes(usb, &input, &output))
        reply = exchange_rfc_version(usb, input, output);
    status = (*usb)->USBInterfaceClose(usb);
    if (status != kIOReturnSuccess && reply) {
        Py_DECREF(reply);
        return io_error("Closing DiCE interface", status);
    }
    return reply;
}

static PyObject *rfc_version_reply(PyObject *self, PyObject *args) {
    io_service_t service = rfc_interface();
    if (!service)
        return NULL;
    IOCFPlugInInterface **plugin = NULL;
    SInt32 score;
    IOReturn status = IOCreatePlugInInterfaceForService(
        service, kIOUSBInterfaceUserClientTypeID, kIOCFPlugInInterfaceID, &plugin, &score);
    if (status != kIOReturnSuccess) {
        IOObjectRelease(service);
        return io_error("Creating USB interface plug-in", status);
    }
    USBInterface usb = NULL;
    HRESULT query = (*plugin)->QueryInterface(
        plugin, CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID182), (LPVOID *)&usb);
    PyObject *result = NULL;
    if (query == S_OK && usb) {
        result = read_from_interface(usb);
        (*usb)->Release(usb);
    } else {
        io_error("Querying USB interface", query);
    }
    IODestroyPlugInInterface(plugin);
    IOObjectRelease(service);
    return result;
}

static PyMethodDef methods[] = {
    {"devices", devices, METH_NOARGS, "Read cached descriptors for matching DiCE adapters."},
    {"rfc_version_reply", rfc_version_reply, METH_NOARGS, "Read exactly one DiCE RFC version reply."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, .m_name = "_iokit", .m_size = -1, .m_methods = methods
};

PyMODINIT_FUNC PyInit__iokit(void) {
    return PyModule_Create(&module);
}
