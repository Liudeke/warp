# include parent path
import os
import sys
import numpy as np
import math
import ctypes

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import warp as wp

wp.init()


@wp.kernel
def basic(x: wp.array(dtype=float)):
    
    tid = wp.tid()

    wp.store(x, tid, float(tid)*1.0)


device = "cuda"
n = 32

x = wp.zeros(n, dtype=float, device="cuda")

wp.launch(
    kernel=basic, 
    dim=n, 
    inputs=[x], 
    device=device)

print(x.to("cpu").numpy())

# redefine kernel
@wp.kernel
def basic(x: wp.array(dtype=float)):
    
    tid = wp.tid()

    wp.store(x, tid, float(tid)*2.0)
    

wp.launch(
    kernel=basic, 
    dim=n, 
    inputs=[x], 
    device=device)

print(x.to("cpu").numpy())