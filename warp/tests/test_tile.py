import numpy as np
import warp as wp

import torch

wp.init()
wp.set_module_options({"enable_backward": True})
wp.set_device("cuda:0")
wp.set_module_options({"fast_math": True})
#wp.config.mode = "debug"
#wp.config.verify_cuda = True

wp.build.clear_kernel_cache()

TILE_M = wp.constant(8)
TILE_N = wp.constant(4)
TILE_K = wp.constant(8)

# num threads per-tile
TILE_DIM = 64

@wp.kernel
def tile_copy(A: wp.array2d(dtype=float),
              B: wp.array2d(dtype=float)):
    
    # tile index
    i, j = wp.tid() 
    
    a = wp.tile_load(A, i, j, m=TILE_M, n=TILE_N)
    wp.tile_store(B, i, j, a)


def test_tile_copy():

    rng = np.random.default_rng(42)

    M = TILE_M*7
    N = TILE_N*5

    A = rng.random((M, N), dtype=np.float32)
    B = rng.random((M, N), dtype=np.float32)

    A_wp = wp.array(A, requires_grad=True)
    B_wp = wp.array(B, requires_grad=True)

    with wp.Tape() as tape:
        wp.launch(tile_copy, dim=[int(M/TILE_M), int(N/TILE_N)], inputs=[A_wp, B_wp], tile_size=TILE_DIM)

    # verify forward pass
    assert(np.allclose(A, B_wp.numpy(), rtol=1.e-4))
    print("Copy forward passed")

    # verify backward pass
    B_wp.grad = wp.ones_like(B_wp)
    tape.backward()

    assert(np.allclose(A_wp.grad.numpy(), B_wp.grad.numpy()))
    print("Copy backward passed")

@wp.func
def unary_func(x: float):
    return wp.sin(x)

@wp.kernel
def tile_unary_map(input: wp.array2d(dtype=float),
                   output: wp.array2d(dtype=float)):
    
    # tile index
    i, j = wp.tid() 
    
    a = wp.tile_load(input, i, j, m=TILE_M, n=TILE_N)
    
    sa = wp.tile_map(wp.sin, a)
    
    wp.tile_store(output, i, j, sa)


def test_tile_unary_map():

    rng = np.random.default_rng(42)

    M = TILE_M*7
    N = TILE_N*5

    A = rng.random((M, N), dtype=np.float32)
    B = np.sin(A)

    A_grad = np.cos(A)

    A_wp = wp.array(A, requires_grad=True)
    B_wp = wp.zeros_like(A_wp, requires_grad=True)

    with wp.Tape() as tape:
        wp.launch(tile_unary_map, dim=[int(M/TILE_M), int(N/TILE_N)], inputs=[A_wp, B_wp], tile_size=TILE_DIM)

    # verify forward pass
    assert(np.allclose(B, B_wp.numpy(), atol=1.e-4))
    print("Unary map forward passed")

    # verify backward pass
    B_wp.grad = wp.ones_like(B_wp)
    tape.backward()

    assert(np.allclose(A_wp.grad.numpy(), A_grad))
    print("Unary map backward passed")


@wp.func
def binary_func(x: float, y: float):
    return wp.sin(x) + y

@wp.kernel
def tile_binary_map(input_a: wp.array2d(dtype=float),
                   input_b: wp.array2d(dtype=float),
                   output: wp.array2d(dtype=float)):
    
    # tile index
    i, j = wp.tid() 
    
    a = wp.tile_load(input_a, i, j, m=TILE_M, n=TILE_N)
    b = wp.tile_load(input_b, i, j, m=TILE_M, n=TILE_N)
    
    sa = wp.tile_map(binary_func, a, b)
    
    wp.tile_store(output, i, j, sa)


def test_tile_binary_map():

    rng = np.random.default_rng(42)

    M = TILE_M*7
    N = TILE_N*5

    A = rng.random((M, N), dtype=np.float32)
    B = rng.random((M, N), dtype=np.float32)
    C = np.sin(A) + B

    A_grad = np.cos(A)
    B_grad = np.ones_like(B)

    A_wp = wp.array(A, requires_grad=True)
    B_wp = wp.array(B, requires_grad=True)
    C_wp = wp.zeros_like(A_wp, requires_grad=True)

    with wp.Tape() as tape:
        wp.launch(tile_binary_map, dim=[int(M/TILE_M), int(N/TILE_N)], inputs=[A_wp, B_wp, C_wp], tile_size=TILE_DIM)

    # verify forward pass
    assert(np.allclose(C, C_wp.numpy(), rtol=1.e-4))
    print("Binary map forward passed")

    # verify backward pass
    C_wp.grad = wp.ones_like(C_wp)
    tape.backward()

    assert(np.allclose(A_wp.grad.numpy(), A_grad, rtol=1.e-2))
    assert(np.allclose(B_wp.grad.numpy(), B_grad, rtol=1.e-2))
    
    print("Binary map backward passed")


@wp.kernel
def tile_grouped_gemm(A: wp.array3d(dtype=float),
                      B: wp.array3d(dtype=float),
                      C: wp.array3d(dtype=float)):

    # output tile index
    i = wp.tid()

    a = wp.tile_load(A[i], 0, 0, m=TILE_M, n=TILE_K)
    b = wp.tile_load(B[i], 0, 0, m=TILE_K, n=TILE_N)

    sum = wp.tile_zeros(m=TILE_M, n=TILE_N, dtype=wp.float32)

    wp.tile_matmul(a, b, sum)

    wp.tile_store(C[i], 0, 0, sum)


def test_tile_batched_gemm():

    batch_count = 56

    M = TILE_M
    N = TILE_N
    K = TILE_K

    rng = np.random.default_rng(42)
    A = rng.random((batch_count, M, K), dtype=np.float32)
    B = rng.random((batch_count, K, N), dtype=np.float32)
    C = np.zeros((batch_count, M, N), dtype=np.float32)

    A_wp = wp.array(A, requires_grad=True)
    B_wp = wp.array(B, requires_grad=True)
    C_wp = wp.array(C, requires_grad=True)

    with wp.Tape() as tape:    
        wp.launch(tile_grouped_gemm, dim=batch_count, inputs=[A_wp, B_wp, C_wp], tile_size=TILE_DIM)

    # bring back to host
    C_host = C_wp.numpy()

    # GEMM forward passed
    print("batched matmul forward passed")


@wp.kernel
def tile_gemm(A: wp.array2d(dtype=float),
              B: wp.array2d(dtype=float),
              C: wp.array2d(dtype=float)):

    # output tile index
    i, j = wp.tid()

    sum = wp.tile_zeros(m=TILE_M, n=TILE_N, dtype=wp.float32)

    M = A.shape[0]
    N = B.shape[1]
    K = A.shape[1]

    count = int(K / TILE_K) 
    
    for k in range(0, count):

        a = wp.tile_load(A, i, k, m=TILE_M, n=TILE_K)
        b = wp.tile_load(B, k, j, m=TILE_K, n=TILE_N)

        # sum += a*b
        wp.tile_matmul(a, b, sum)

    wp.tile_store(C, i, j, sum)


def test_tile_gemm():

    M = TILE_M*7
    K = TILE_K*6
    N = TILE_N*5

    rng = np.random.default_rng(42)
    A = rng.random((M, K), dtype=np.float32)
    B = rng.random((K, N), dtype=np.float32)
    C = np.zeros((M, N), dtype=np.float32)

    A_wp = wp.array(A, requires_grad=True)
    B_wp = wp.array(B, requires_grad=True)
    C_wp = wp.array(C, requires_grad=True)

    with wp.Tape() as tape:    
        wp.launch(tile_gemm, dim=(int(M/TILE_M), int(N/TILE_N)), inputs=[A_wp, B_wp, C_wp], tile_size=TILE_DIM)

    assert(np.allclose(A@B, C_wp.numpy(), rtol=1.e-4))

    # GEMM forward passed
    print("matmul forward passed")

    adj_C = np.ones_like(C)

    tape.backward(grads={C_wp: wp.array(adj_C)})

    assert(np.allclose(adj_C@B.T, A_wp.grad.numpy(), rtol=1.e-4))
    assert(np.allclose(A.T@adj_C, B_wp.grad.numpy(), rtol=1.e-4))

    print("matmul backward passed")



@wp.kernel
def tile_operators(input: wp.array3d(dtype=float),
                   output: wp.array3d(dtype=float)):

    # output tile index
    i = wp.tid()

    a = wp.tile_load(input[i], 0, 0, m=TILE_M, n=TILE_N)
    
    # neg
    b = -a

    # right scalar multiply
    c = b*0.5

    # left scalar multiply
    d = 0.5*c

    # add tiles
    e = a + d
    
    wp.tile_store(output[i], 0, 0, e)


def test_tile_operators():

    batch_count = 56

    M = TILE_M
    N = TILE_N

    rng = np.random.default_rng(42)
    input = rng.random((batch_count, M, N), dtype=np.float32)
    output = input*0.75

    input_wp = wp.array(input)
    output_wp = wp.zeros_like(input_wp)

    wp.launch(tile_operators, dim=batch_count, inputs=[input_wp, output_wp], tile_size=TILE_DIM)

    assert(np.allclose(output, output_wp.numpy(), rtol=1.e-4))

    print("operators forward passed")



test_tile_copy()
test_tile_unary_map()
test_tile_binary_map()
test_tile_batched_gemm()
test_tile_gemm()
test_tile_operators()