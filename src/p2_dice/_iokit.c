#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <libkern/OSByteOrder.h>

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

static PyObject *configurations(io_service_t service) {
    IOCFPlugInInterface **plugin = NULL;
    SInt32 score;
    IOReturn status = IOCreatePlugInInterfaceForService(
        service, kIOUSBDeviceUserClientTypeID, kIOCFPlugInInterfaceID, &plugin, &score);
    if (status != kIOReturnSuccess)
        return io_error("Creating USB descriptor plug-in", status);

    IOUSBDeviceInterface **device = NULL;
    HRESULT query = (*plugin)->QueryInterface(
        plugin, CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID100), (LPVOID *)&device);
    if (query != S_OK || !device) {
        IODestroyPlugInInterface(plugin);
        return io_error("Querying USB descriptor interface", query);
    }

    UInt8 count = 0;
    PyObject *result = NULL;
    status = (*device)->GetNumberOfConfigurations(device, &count);
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
        IOUSBConfigurationDescriptorPtr descriptor = NULL;
        status = (*device)->GetConfigurationDescriptorPtr(device, index, &descriptor);
        if (status != kIOReturnSuccess) {
            io_error("Getting configuration descriptor", status);
            Py_CLEAR(result);
            break;
        }
        if (!descriptor || descriptor->bLength < 9 || descriptor->bDescriptorType != 2 ||
            OSSwapLittleToHostInt16(descriptor->wTotalLength) < descriptor->bLength) {
            PyErr_SetString(PyExc_ValueError, "invalid configuration descriptor header");
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

static int append_device(PyObject *devices, io_service_t service) {
    int64_t vendor = number_property(service, CFSTR(kUSBVendorID));
    int64_t product = number_property(service, CFSTR(kUSBProductID));
    if (vendor != 0x17aa || product != 0xd1ce)
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
    PyObject *row = Py_BuildValue("(iiiiiiN)", (int)vendor, (int)product, (int)usb,
                                  (int)release, bus, address >= 0 && address <= 127 ? (int)address : -1,
                                  configs);
    if (!row)
        return -1;
    int status = PyList_Append(devices, row);
    Py_DECREF(row);
    return status;
}

static PyObject *devices(PyObject *self, PyObject *args) {
    CFMutableDictionaryRef match = IOServiceMatching(kIOUSBHostDeviceClassName);
    if (!match)
        return PyErr_NoMemory();
    io_iterator_t iter = IO_OBJECT_NULL;
    IOReturn status = IOServiceGetMatchingServices(kIOMainPortDefault, match, &iter);
    if (status != kIOReturnSuccess)
        return io_error("Matching USB devices", status);

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

static PyMethodDef methods[] = {
    {"devices", devices, METH_NOARGS, "Read cached descriptors for matching DiCE adapters."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, .m_name = "_iokit", .m_size = -1, .m_methods = methods
};

PyMODINIT_FUNC PyInit__iokit(void) {
    return PyModule_Create(&module);
}
