#include <Python.h>

#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>

#include "femApi.h"

/*
 * A simple structure to be used as an opaque pointer to a FEM object in API
 * calls. This wraps the real handle, which can then be set to NULL if the
 * user explicitly calls close(), and tested in methods accordingly.
*/
typedef struct Fem {
    void* handle;
} Fem;
typedef Fem* FemPtr;

/* Forward declarations */
static void _del(PyObject* obj);

/* An exception object to be raised by the API wrapper */
static PyObject* fem_api_error;

/* Helper function to format the API exception error message using printf() style arguments */
#define MAX_ERR_STRING_LEN 128
void _set_api_error_string(const char* format, ...) {
    char err_str[MAX_ERR_STRING_LEN];
    va_list arglist;
    va_start(arglist, format);
    vsnprintf(err_str, MAX_ERR_STRING_LEN, format, arglist);
    va_end(arglist);
    PyErr_SetString(fem_api_error, err_str);
}

/* Helper to validate the opaque FEM pointer object and the handle it contains */
#define _validate_ptr_and_handle(ptr, func_name) \
    if (ptr == NULL) { \
        _set_api_error_string("%s: resolved FEM object pointer to null", func_name); \
        return NULL; } \
    if (ptr->handle == NULL) { \
        _set_api_error_string("%s: FEM object pointer has null FEM handle", func_name); \
        return NULL; }

static PyObject* _initialise(PyObject* self, PyObject* args)
{
    int id;

    if (!PyArg_ParseTuple(args, "i", &id)) {
        return NULL;
    }

    FemPtr fem_ptr = malloc(sizeof(Fem));
    if (fem_ptr == NULL) {
        PyErr_SetString(fem_api_error, "Unable to malloc() space for FEM object");
        return NULL;
    }

    fem_ptr->handle = femInitialise(id);
    if (fem_ptr->handle == NULL) {
        PyErr_SetString(fem_api_error, femErrorMsg());
        return NULL;
    }
    //printf("Initialised module with handle %lu\n", (unsigned long)(fem_ptr->handle));

    return PyCapsule_New(fem_ptr, "FemPtr", _del);
}

static PyObject* _get_id(PyObject* self, PyObject* args)
{

    PyObject* _handle;
    FemPtr fem_ptr;
    int id;

    if (!PyArg_ParseTuple(args, "O", &_handle)) {
        return NULL;
    }

    fem_ptr = (FemPtr) PyCapsule_GetPointer(_handle, "FemPtr");
    _validate_ptr_and_handle(fem_ptr, "_get_id");

    id = femGetId(fem_ptr->handle);
    return Py_BuildValue("i", id);
}

static PyObject* _get_int(PyObject* self, PyObject* args)
{
    int rc;
    PyObject* _handle;
    int chip_id, param_id, size;
    FemPtr fem_ptr;

    int* value_ptr;
    PyObject* values;

    if (!PyArg_ParseTuple(args, "Oiii", &_handle, &chip_id, &param_id, &size)) {
        return NULL;
    }
    //printf("_get_int: chip_id %d param_id %d size %d\n", chip_id, param_id, size);

    fem_ptr = (FemPtr) PyCapsule_GetPointer(_handle, "FemPtr");
    _validate_ptr_and_handle(fem_ptr, "_get_int");

    value_ptr = (int *)malloc(size * sizeof(int));
    if (value_ptr == NULL) {
        _set_api_error_string("get_int: unable to allocate space for %d integer values in get_int", size);
        return NULL;
    }

    rc = femGetInt(fem_ptr->handle, chip_id, param_id, size, value_ptr);

    values = PyList_New(size);
    if (rc == FEM_RTN_OK) {
        int ival;
        for (ival = 0; ival < size; ival++) {
            PyList_SetItem(values, ival, PyInt_FromLong(value_ptr[ival]));
        }
    }
    free(value_ptr);

    return Py_BuildValue("iO", rc, values);
}

static PyObject* _cmd(PyObject* self, PyObject* args)
{
    PyObject* _handle;
    FemPtr fem_ptr;
    int chipId, cmdId;
    int rc;

    if (!PyArg_ParseTuple(args, "Oii", &_handle, &chipId, &cmdId)) {
        return NULL;
    }

    fem_ptr = (FemPtr) PyCapsule_GetPointer(_handle, "FemPtr");
    _validate_ptr_and_handle(fem_ptr, "_cmd");

    rc = femCmd(fem_ptr->handle, chipId, cmdId);

    return Py_BuildValue("i", rc);
}

static PyObject* _close(PyObject* self, PyObject* args)
{
    PyObject* _handle;
    FemPtr fem_ptr;

    if (!PyArg_ParseTuple(args, "O", &_handle)) {
        return NULL;
    }

    fem_ptr = (FemPtr) PyCapsule_GetPointer(_handle, "FemPtr");
    _validate_ptr_and_handle(fem_ptr, "_close");

    femClose(fem_ptr->handle);
    fem_ptr->handle = NULL;

    return Py_BuildValue("");
}

static void _del(PyObject* obj)
{
    FemPtr fem_ptr = (FemPtr) PyCapsule_GetPointer(obj, "FemPtr");
    if (fem_ptr == NULL) {
        return;
    }

    if (fem_ptr->handle != NULL) {
        femClose(fem_ptr->handle);
    }
}

/*  define functions in module */
static PyMethodDef FemApiMethods[] =
{
     {"initialise", _initialise, METH_VARARGS, "initialise a module"},
     {"get_id",     _get_id,     METH_VARARGS, "get a module ID"},
     {"get_int",    _get_int,    METH_VARARGS, "get one or more integer parameters"},
     {"cmd",        _cmd,        METH_VARARGS, "issue a command to a module"},
     {"close",      _close,      METH_VARARGS, "close a module"},
     {NULL, NULL, 0, NULL}
};

/* module initialization */
PyMODINIT_FUNC
initfem_api(void)
{
    PyObject* m;
    m = Py_InitModule("fem_api", FemApiMethods);
    if (m == NULL) {
        return;
    }

    fem_api_error = PyErr_NewException("fem_api.error", NULL, NULL);
    Py_INCREF(fem_api_error);
    PyModule_AddObject(m, "error", fem_api_error);
}