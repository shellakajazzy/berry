# ~/~ begin <<README.md#models.py>>[init]
# /// script
# dependencies = [
#   "numpy",
#   "pyopencl"
# ]
# ///

import numpy as np
import pyopencl as cl
import sys

# ~/~ begin <<README.md#select-opencl-device>>[init]
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
# ~/~ end
# ~/~ begin <<README.md#opencl-initialization>>[init]
cl_ctx = cl.Context([device])
cl_queue = cl.CommandQueue(cl_ctx)
cl_pgrm = cl.Program(cl_ctx, """
// ~/~ begin <<README.md#opencl-kernels>>[init]
__kernel void nrlNetMatMulFP32(
    const unsigned int layer_len,
    const unsigned int weights_per_node,

    const unsigned int activations_offset,
    const unsigned int weights_offset,
    const unsigned int biases_offset,

    __global float* activations,
    __global float* weights,
    __global float* biases
) {

    return;
}
// ~/~ end
""").build()
# ~/~ end
# ~/~ begin <<README.md#neural-networks>>[init]
class NeuralNetworkFP32:
    def __init__(self, cl_ctx, cl_queue, cl_pgrm, layer_lens):
        activations = 0
        weights = 0
        biases = 0
        for i, layer_len in enumerate(layer_lens):
            activations += layer_len
            if i <= 0: continue
            weights += layer_len * layer_lens[i - 1]
            biases += layer_len

        self.layer_lens = layer_lens
        self.cl_ctx = cl_ctx
        self.cl_queue = cl_queue
        self.cl_pgrm = cl_pgrm

        self.activations = np.random.rand(activations).astype(np.float32)
        self.weights = np.random.rand(weights).astype(np.float32)
        self.biases = np.random.rand(biases).astype(np.float32)
        self.cl_activations = cl.Buffer(self.cl_ctx, cl.mem_flags.USE_HOST_PTR, hostbuf=self.activations)
        self.cl_weights = cl.Buffer(self.cl_ctx, cl.mem_flags.USE_HOST_PTR, hostbuf=self.cl_weights)
        self.cl_biases = cl.Buffer(self.cl_ctx, cl.mem_flags.USE_HOST_PTR, hostbuf=self.cl_biases)
    # ~/~ begin <<README.md#neural-network-forward-pass>>[init]
    def forward_pass(self, input_activations):
        if input_activations.dtype != np.float32: return
    
        activations_offset = 0
        weights_offset = 0
        biases_offset = 0
    
        for i, input_activation in enumerate(input_activations): activations[i] == input_activation
        activations_offset += len(input_activations)
    
        for i, layer_len in enumerate(self.layer_lens):
            if i == 0: continue
            prev_layer_len = layer_lens[i - 1]
    
            # TODO, run the matmul
    
            activations_offset += layer_len
            weights_offset += layer_len * prev_layer_len
            biases_offset += layer_len
    # ~/~ end
# ~/~ end
# ~/~ end
