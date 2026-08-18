# berry
An system of AIs put together for the purpose of entertainment

## Models
This is the source code and documentation for the models used to have berry interact with the world.

[models.py](./models.py):
``` {.python file=models.py}
# /// script
# dependencies = [
#   "numpy",
#   "pyopencl"
# ]
# ///

import numpy as np
import pyopencl as cl
import sys

<<select-opencl-device>>
<<opencl-initialization>>
<<neural-networks>>
```

## OpenCL Setup

First, we need to select which OpenCL device we will be using.

`select-opencl-device`:
``` {.python #select-opencl-device}
possible_devices = []

platforms = cl.get_platforms()
for platform in platforms:
    devices = platform.get_devices()
    for device in devices: possible_devices += [device]

device = None
if len(possible_devices) == 0:
    print("No OpenCL devices found")
    sys.exit(1)
elif len(possible_devices) == 1:
    device = possible_devices[0]
    print(f"Only 1 OpenCL device found, using: {device.name}")
else:
    while True:
        print("Select an OpenCL device to run on:")
        for i, device in enumerate(possible_devices): print(f"{i}: {device.name}")
        selected_idx = input("Enter the index of the selected device: ")
        try:
            device = possible_devices[int(selected_idx)]
            print(f"Using device: {device.name}")
            break
        except:
            print("\n\n")
            print(f"ERROR: must select a number from 0-{len(possible_devices) - 1} (inclusive)")
            continue
```


Then, the OpenCL program needs to be built.

`opencl-initialization`:
``` {.python #opencl-initialization}
cl_ctx = cl.Context([device])
cl_queue = cl.CommandQueue(cl_ctx)
cl_pgrm = cl.Program(cl_ctx, """
""").build()
```