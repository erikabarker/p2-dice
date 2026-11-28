#include <stdint.h>
#include <time.h>
#include <IOKit/IOKitLib.h>

static kern_return_t no_services(mach_port_t port, CFDictionaryRef match, io_iterator_t *iter) {
    CFRelease(match);
    *iter = IO_OBJECT_NULL;
    return kIOReturnSuccess;
}

#define IOServiceGetMatchingServices no_services
static uint64_t simulated_time(clockid_t clock);
static io_object_t next_service(io_iterator_t iter);
static boolean_t valid_iterator(io_iterator_t iter);
static kern_return_t release_service(io_object_t service);
#define IOIteratorNext next_service
#define IOIteratorIsValid valid_iterator
#define IOObjectRelease release_service
#define clock_gettime_nsec_np simulated_time
#include "../src/p2_dice/_iokit.c"
#undef clock_gettime_nsec_np

static const char *scenario;
static unsigned int opens, closes, writes, reads;
static uint64_t now;

static bool scenario_is(const char *name) {
    return strcmp(scenario, name) == 0;
}

static uint64_t simulated_time(clockid_t clock) {
    if (scenario_is("deadline") && reads != 0)
        now += 2000000001;
    return now;
}

static IOReturn open_interface(void *self) {
    opens++;
    return scenario_is("occupied") ? kIOReturnExclusiveAccess : kIOReturnSuccess;
}

static IOReturn close_interface(void *self) {
    closes++;
    return kIOReturnSuccess;
}

static IOReturn config(void *self, UInt8 *value) {
    *value = 1;
    return kIOReturnSuccess;
}

static IOReturn number(void *self, UInt8 *value) {
    *value = 0;
    return kIOReturnSuccess;
}

static IOReturn alternate(void *self, UInt8 *value) {
    *value = scenario_is("wrong-alt") || (scenario_is("changed-alt") && opens);
    return kIOReturnSuccess;
}

static IOReturn endpoints(void *self, UInt8 *value) {
    *value = 2;
    return kIOReturnSuccess;
}

static IOReturn properties(void *self, UInt8 pipe, UInt8 *direction, UInt8 *number,
                           UInt8 *type, UInt16 *packet, UInt8 *interval) {
    if (pipe != 1 && pipe != 2)
        return kIOReturnBadArgument;
    *direction = pipe == 1 || scenario_is("duplicate-out") ? kUSBOut : kUSBIn;
    *number = 1;
    *type = scenario_is("interrupt") ? kUSBInterrupt : kUSBBulk;
    *packet = scenario_is("wrong-packet-size") ? 64 : 512;
    *interval = 0;
    return kIOReturnSuccess;
}

static IOReturn write_pipe(void *self, UInt8 pipe, void *buffer, UInt32 size,
                           UInt32 no_data, UInt32 completion) {
    const uint8_t expected[] = {0xb5, 0x02, 0x00, 0x20, 0x00, 0x69};
    writes++;
    if (pipe != 1 || size != sizeof(expected) || memcmp(buffer, expected, sizeof(expected)) ||
        !no_data || !completion || no_data > 1000 || completion > 1000)
        return kIOReturnBadArgument;
    return scenario_is("write-error") ? kIOReturnError : kIOReturnSuccess;
}

static IOReturn read_pipe(void *self, UInt8 pipe, void *buffer, UInt32 *size,
                          UInt32 no_data, UInt32 completion) {
    const uint8_t reply[] = {0xb5, 6, 0, 0x24, 0, 0, 2, 3, 4, 0x72};
    reads++;
    if (pipe != 2 || *size != 512 || !no_data || !completion || no_data > 2000 || completion > 2000)
        return kIOReturnBadArgument;
    if (scenario_is("read-error"))
        return kIOReturnError;
    if (scenario_is("empty")) {
        *size = 0;
        return kIOReturnSuccess;
    }
    if (scenario_is("extra")) {
        *size = 11;
        return kIOReturnSuccess;
    }
    *size = reads == 1 ? 4 : 6;
    memcpy(buffer, reply + (reads == 1 ? 0 : 4), *size);
    return kIOReturnSuccess;
}

static PyObject *exchange(void) {
    IOUSBInterfaceInterface182 table = {
        .GetConfigurationValue = config, .GetInterfaceNumber = number,
        .GetAlternateSetting = alternate, .GetNumEndpoints = endpoints,
        .USBInterfaceOpen = open_interface, .USBInterfaceClose = close_interface,
        .GetPipeProperties = properties, .WritePipeTO = write_pipe, .ReadPipeTO = read_pipe,
    };
    IOUSBInterfaceInterface182 *interface = &table;
    return read_from_interface(&interface);
}

static PyObject *simulate(PyObject *self, PyObject *name) {
    scenario = PyUnicode_AsUTF8(name);
    if (!scenario)
        return NULL;
    reads = writes = opens = closes = 0;
    now = 1000000000;
    return exchange();
}

static PyObject *calls;
static void record(const char *name) {
    PyObject *entry = PyUnicode_FromString(name);
    if (entry) {
        PyList_Append(calls, entry);
        Py_DECREF(entry);
    }
}

static IOReturn device_config(void *self, UInt8 *value) {
    bool owned = PyList_Size(calls) > 0;
    record("get");
    if (scenario_is("get-error") || (owned && scenario_is("recheck-error")))
        return kIOReturnNoDevice;
    *value = scenario_is("already") || (owned && scenario_is("became-active")) ? 1 :
        scenario_is("other") || (owned && scenario_is("became-other")) ? 2 : 0;
    return kIOReturnSuccess;
}

static IOReturn device_open(void *self) {
    record("open");
    return scenario_is("device-busy") ? kIOReturnExclusiveAccess : kIOReturnSuccess;
}

static IOReturn device_close(void *self) {
    record("close");
    return scenario_is("close-error") ? kIOReturnError : kIOReturnSuccess;
}

static IOReturn config_count(void *self, UInt8 *value) {
    record("count");
    *value = 2;
    return kIOReturnSuccess;
}

static IOReturn config_descriptor(void *self, UInt8 index, IOUSBConfigurationDescriptorPtr *result) {
    static IOUSBConfigurationDescriptor descriptor;
    record("descriptor");
    if (index >= 2)
        return kIOReturnBadArgument;
    descriptor = (IOUSBConfigurationDescriptor) {
        .bLength = 9, .bDescriptorType = 2,
        .wTotalLength = OSSwapHostToLittleInt16(scenario_is("bad-descriptor") ? 1 : 9),
        .bConfigurationValue = index == 0 || scenario_is("missing") ? 3 : 1
    };
    *result = &descriptor;
    return kIOReturnSuccess;
}

static IOReturn set_config(void *self, UInt8 value) {
    record("set");
    return value != 1 || scenario_is("selection-error") ? kIOReturnBadArgument : kIOReturnSuccess;
}

static IOReturn interface_iterator(void *self, IOUSBFindInterfaceRequest *req, io_iterator_t *iter) {
    record("iterator");
    if (req->bAlternateSetting != 0 || scenario_is("iterator-error"))
        return kIOReturnBadArgument;
    *iter = scenario_is("no-iterator") ? IO_OBJECT_NULL : 4;
    return kIOReturnSuccess;
}

static PyObject *activate_and_exchange(PyObject *self, PyObject *name) {
    scenario = PyUnicode_AsUTF8(name);
    if (!scenario)
        return NULL;
    Py_XSETREF(calls, PyList_New(0));
    if (!calls)
        return NULL;
    reads = writes = opens = closes = 0;
    now = 1000000000;
    IOUSBDeviceInterface table = {
        .GetConfiguration = device_config, .USBDeviceOpen = device_open, .USBDeviceClose = device_close,
        .GetNumberOfConfigurations = config_count, .GetConfigurationDescriptorPtr = config_descriptor,
        .SetConfiguration = set_config, .CreateInterfaceIterator = interface_iterator,
    };
    IOUSBDeviceInterface *device = &table;
    if (!active_interfaces(&device))
        return NULL;
    return exchange();
}

static PyObject *device_calls(PyObject *self, PyObject *args) {
    return Py_NewRef(calls);
}

static PyObject *counts(PyObject *self, PyObject *args) {
    return Py_BuildValue("(IIII)", opens, writes, reads, closes);
}

static unsigned int cursor, service_count, releases[5];

static io_object_t next_service(io_iterator_t iter) {
    return cursor < service_count ? ++cursor : IO_OBJECT_NULL;
}

static boolean_t valid_iterator(io_iterator_t iter) {
    return !scenario_is("changed");
}

static kern_return_t release_service(io_object_t service) {
    if (service >= 5)
        return kIOReturnBadArgument;
    releases[service]++;
    return kIOReturnSuccess;
}

static bool target(io_service_t service) {
    return service != 1;
}

static PyObject *select_service(PyObject *self, PyObject *name) {
    scenario = PyUnicode_AsUTF8(name);
    if (!scenario)
        return NULL;
    cursor = 0;
    service_count = scenario_is("two") ? 3 : scenario_is("none") ? 1 : 2;
    memset(releases, 0, sizeof(releases));
    io_service_t selected = unique_match(4, target, "fixture device");
    if (!selected)
        return NULL;
    release_service(selected);
    return PyLong_FromUnsignedLong(selected);
}

static PyObject *release_counts(PyObject *self, PyObject *args) {
    return Py_BuildValue("(IIII)", releases[1], releases[2], releases[3], releases[4]);
}

static PyMethodDef fake_methods[] = {
    {"devices", devices, METH_NOARGS, NULL},
    {"rfc_version_reply", rfc_version_reply, METH_NOARGS, NULL},
    {"select_service", select_service, METH_O, NULL}, {"release_counts", release_counts, METH_NOARGS, NULL},
    {"activate_and_exchange", activate_and_exchange, METH_O, NULL},
    {"device_calls", device_calls, METH_NOARGS, NULL},
    {"simulate", simulate, METH_O, NULL}, {"counts", counts, METH_NOARGS, NULL}, {NULL}
};
static struct PyModuleDef fake_module = {
    PyModuleDef_HEAD_INIT, .m_name = "_rfc_fixture", .m_size = -1, .m_methods = fake_methods
};
PyMODINIT_FUNC PyInit__rfc_fixture(void) {
    return PyModule_Create(&fake_module);
}
