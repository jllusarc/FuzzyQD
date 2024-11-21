import numpy as np
import time 
import os
import pickle
import h5py
import math
import matplotlib.pyplot as plt
from scipy.ndimage import rotate
from itertools import permutations
from joblib import Parallel, delayed

#%% Function definitions

"""Library of definitions needed for Bloch state expansion calculations"""

def _getline(cube):
    """
    Read a line from cube file where the first field is an int 
    and the remaining fields are floats.

    Parameters:
    cube (file object): File object of the cube file.

    Returns:
    tuple: (int, list of float), where the first element is an integer and the second is a list of floats.
    """
    line = cube.readline().strip().split()
    return int(line[0]), list(map(float, line[1:]))

def read_dummy_cube(path):
    """
    Reads data from a cube file and returns the data along with metadata.

    Parameters:
    path (str): The path to the cube file.

    Returns:
    tuple: Data in a 3D numpy array, metadata dictionary.
    """
    start_time = time.time()
    meta = {}
    
    with open(path, 'r') as cube:
        # Skip header lines
        cube.readline(); cube.readline()
        
        # Read grid dimensions and origin
        natm, meta['org'] = _getline(cube)
        
        # Read x, y, z coordinate information
        nx, meta['xvec'] = _getline(cube)
        ny, meta['yvec'] = _getline(cube)
        nz, meta['zvec'] = _getline(cube)
        meta['N_x'], meta['N_y'], meta['N_z'] = nx, ny, nz
        
        # Read data in a more efficient way
        data = np.fromiter((float(val) for line in cube for val in line.strip().split()), dtype=float)
        data = data.reshape((nx, ny, nz))
    
    end_time = time.time()
    print(f"read_dummy_cube executed in {end_time - start_time:.6f} seconds")
    return data, meta

def read_cube(fname):
    """
    Reads all information from a cube file, including metadata, atomic information, and grid data.

    Parameters:
    fname (str): The path to the cube file.

    Returns:
    tuple: Data in a 3D numpy array, metadata dictionary, atomic numbers array, atomic positions array, and a boolean indicating success.
    """
    start_time = time.time()
    meta = {}
    no_error = True
    
    try:
        with open(fname, 'r') as cube:
            # Ignore comment lines
            cube.readline(); cube.readline()
            
            # Read coordinate data
            natm, meta['org'] = _getline(cube)
            nx, meta['xvec'] = _getline(cube)
            ny, meta['yvec'] = _getline(cube)
            nz, meta['zvec'] = _getline(cube)
            meta['N_x'], meta['N_y'], meta['N_z'], meta['N'] = nx, ny, nz, natm
            
            # Read atomic information
            atom_Z = np.zeros(natm, dtype=int)
            atom_pos = np.zeros((natm, 3), dtype=float)
            for i in range(natm):
                line = cube.readline().strip().split()
                atom_Z[i] = int(line[0])
                atom_pos[i, :] = list(map(float, line[2:]))
            
            # Read data in a more efficient way
            data = np.fromiter((float(val) for line in cube for val in line.strip().split()), dtype=float)
            data = data.reshape((nx, ny, nz))
    
    except FileNotFoundError:
        no_error = False
        data, atom_Z, atom_pos = np.array([]), np.array([]), np.array([])
    
    end_time = time.time()
    print(f"read_cube executed in {end_time - start_time:.6f} seconds")
    return data, meta, atom_Z, atom_pos, no_error

def log_output(log_string, log_file):

    print(log_string)
    with open(log_file, 'a') as log:
        log.write(log_string + '\n')
    return

def set_index(e_k):
    """
    Calculate the crystallographic indices of a direction in reciprocal space characterized by the direction vector `e_k`.

    Parameters:
    e_k (numpy.ndarray): A 1D array representing the direction vector in reciprocal space.

    Returns:
    tuple: A tuple containing the following:
        - index (numpy.ndarray): The crystallographic indices scaled by the minimum non-zero element of `e_k`.
        - label (int): A label calculated as the sum of the absolute values of the scaled indices minus 1.
    """
    start_time = time.time()

    # Calculate absolute values of e_k and filter non-zero elements
    abs_e_k = np.abs(e_k)
    abs_e_k_non_zero = abs_e_k[abs_e_k != 0]

    # Find the crystallographic index by dividing by the minimum non-zero value
    min_non_zero = np.min(abs_e_k_non_zero)
    index = e_k / min_non_zero

    # Calculate label as the sum of the absolute values of the index, minus 1
    label = int(np.sum(np.abs(index)) - 1)

    # Print detailed information for verification
    print(f"Input vector (e_k): {e_k}")
    print(f"Crystallographic index (scaled vector): {index}")
    print(f"Label (sum of absolute values of scaled indices - 1): {label}")

    end_time = time.time()
    print(f"set_index executed in {end_time - start_time:.6f} seconds")

    return index, label

def k_path_segment(k1, k2, e_k_dict, dk_set):
    """
    Initialize a segment of the k-path. The segment is defined as part of the line vec(k_0) + kappa * vec(e_k),
    where vec(e_k) gives the direction of the line and vec(k_0) is the position vector of the line, which is taken as
    perpendicular to vec(e_k).

    Parameters:
    k1 (numpy.ndarray): The starting point of the segment in reciprocal space.
    k2 (numpy.ndarray): The ending point of the segment in reciprocal space.
    e_k_dict (dict): Dictionary containing information about direction vectors.
    dk_set (float): Desired spacing between points in reciprocal space.

    Returns:
    dict: A dictionary containing the details of the k-path segment.
    """
    start_time = time.time()

    # Calculate direction vector and normalize it
    e_k = k2 - k1
    norm_k = np.linalg.norm(e_k)
    e_k /= norm_k  # Normalized unit vector along the segment
    print(f"Normalized direction vector (e_k): {e_k}")

    # Identify the segment direction and get the direction label
    index, label = set_index(e_k)
    print(f"Segment direction index: {index}, label: {label}")

    # Determine sign based on direction vectors in e_k_dict
    sign = 1
    vectors = e_k_dict[label]['positive_dir']
    N_d = np.size(vectors, axis=0)
    print(f"Number of direction vectors (N_d): {N_d}")
    for v in range(N_d):
        dot_product = np.dot(e_k, vectors[v, :])
        print(f"Dot product with direction vector {v}: {dot_product}")
        if abs(dot_product) > 0.99999:
            sign = round(dot_product)
    print(f"Sign of the direction: {sign}")
    # Calculate initial and final parallel positions of the segment in BZ1
    kappa_1 = np.dot(k1, e_k)
    kappa_2 = np.dot(k2, e_k)
    print(f"Initial parallel position (kappa_1): {kappa_1}")
    print(f"Final parallel position (kappa_2): {kappa_2}")

    # Get position vector of the line
    k_0 = k1 - kappa_1 * e_k
    print(f"Position vector of the line (k_0): {k_0}")

    # Determine the number of points along the segment
    N_k = closest((kappa_2 - kappa_1) / dk_set)
    dk_real = (kappa_2 - kappa_1) / N_k
    kappa = np.linspace(kappa_1, kappa_2 - dk_real, N_k)
    print(f"Number of points (N_k): {N_k}, Real spacing (dk_real): {dk_real}")

    # Calculate rotation angles
    if label == 0:
        angle_1, angle_2 = 0, 0
    else:
        angle_1 = -np.arcsin(sign * e_k[1] / np.sqrt(e_k[0]**2 + e_k[1]**2))
        angle_2 = -np.arcsin(sign * e_k[2])
    angle = np.array([angle_1, angle_2])
    print(f"Rotation angles: {angle}")

    # Calculate perpendicular basis vectors
    if label == 0:
        k_perp_basis = np.eye(3)
    else:
        k_perp_basis = np.array([
            [np.cos(angle[1]) * np.cos(angle[0]), -np.cos(angle[1]) * np.sin(angle[0]), -np.sin(angle[1])],
            [np.sin(angle[0]), np.cos(angle[0]), 0],
            [np.sin(angle[1]) * np.cos(angle[0]), -np.sin(angle[1]) * np.sin(angle[0]), np.cos(angle[1])]
        ])
    print(f"Perpendicular basis vectors (k_perp_basis):\n{k_perp_basis}")
    # Create dictionary containing the k-path segment information
    k_segment = {
        'dir': label,
        'scale': e_k_dict[label]['scale'],
        'dir_k': e_k,
        'indices': index,
        'pos_k': k_0,
        'kappa_12': [kappa_1, kappa_2],
        'r_par_sign': sign,
        'dk': dk_real,
        'rot_angle': angle,
        'k_perp_basis': k_perp_basis,
        'N_bun': e_k_dict[label]['N_bun'],
        'origin_bun': e_k_dict[label]['origin_bun'],
        'kappa': kappa,
        'phi_folded': np.zeros(N_k)
    }

    end_time = time.time()
    print(f"k_path_segment executed in {end_time - start_time:.6f} seconds")

    return k_segment

def set_r_para_sign(direction, direction_vector, e_k_dict):
    """
    Set the sign of the direction vector relative to the positive directions as defined in e_k_dict.

    Parameters:
    direction (int): The direction index (0, 1, 2).
    direction_vector (numpy.ndarray): A 1D array representing the direction vector.
    e_k_dict (dict): Dictionary containing information about positive direction vectors for each direction.

    Returns:
    int: The sign of the direction vector, either +1 or -1.
    """
    start_time = time.time()

    sign = 1
    for d in range(3):
        vectors = e_k_dict[d]['positive_dir']
        N_d = vectors.shape[0]  # More Pythonic way to get the number of rows
        print(f"Checking direction {d}, Number of vectors (N_d): {N_d}")
        for v in range(N_d):
            dot_product = np.dot(direction_vector, vectors[v, :])
            print(f"Dot product with vector {v} in direction {d}: {dot_product}")
            if abs(dot_product) == 1:
                sign = int(np.sign(dot_product))
                print(f"Sign found: {sign}")

    end_time = time.time()
    print(f"set_r_para_sign executed in {end_time - start_time:.6f} seconds")

    return sign

def summary_k_path(k_path, segments, a_dx):
    """
    Summarize the path through BZ1 by identifying the number of (100), (110), and (111) segments.
    A dictionary is returned that contains the total of each of these segments and the position of these different segments
    in the path.

    Parameters:
    k_path (list of dict): A list where each element is a dictionary containing information about a segment.
    segments (int): The number of segments in the k-path.
    a_dx (float): A parameter used to calculate the Nyquist limit.

    Returns:
    dict: A dictionary containing the total number of each type of segment and their positions in the path.
    """
    start_time = time.time()

    # Initialize arrays to store the number and positions of segments along (100), (110), and (111)
    n_dir = np.zeros(3, dtype=int)  # Number of segments along (100), (110), and (111)
    pos_dir = np.full((3, segments), -1, dtype=int)  # Positions of different segments in the path (-1 for unused slots)

    # Iterate through each segment to classify and count
    for s in range(segments):
        segment = k_path[s]
        d = segment['dir']  # Identify segment type: 0 = (100), 1 = (110), 2 = (111)
        pos_dir[d, n_dir[d]] = s  # Store position of the segment
        n_dir[d] += 1  # Increment the count of the segment type
        print(f"Segment {s}: direction {d}, current count of type {d}: {n_dir[d]}")

    # Calculate Nyquist limit
    Nyq = math.floor(0.5 * ((a_dx / np.sqrt(3)) - 2))
    print(f"Calculated Nyquist limit (Nyq): {Nyq}")

    # Create summary dictionary
    k_structure = {
        'n_dir': n_dir,
        'pos_dir': pos_dir,
        'Nyquist': Nyq
    }

    end_time = time.time()
    print(f"summary_k_path executed in {end_time - start_time:.6f} seconds")
    print("Summary of k-path:")
    print(f"Number of segments (n_dir): {n_dir}")
    print(f"Positions of segments (pos_dir):\n{pos_dir}")
    print(f"Nyquist limit: {Nyq}")

    return k_structure

def rotate_psi(psi, k_segment):
    """
    Orient the wavefunction in line with the specified direction.
    The reorientation creates a cubic grid aligned with the segment axis. For (100), re-orientation is avoided
    through a re-assignment of the axes. This function fills in the parallel and perpendicular coordinates
    in line with the wavefunctions.
    
    Parameters:
    psi (numpy.ndarray): A 3D array representing the wavefunction.
    k_segment (dict): A dictionary containing information about the segment, including direction and rotation angles.

    Returns:
    tuple: A tuple containing the following:
        - psi_rot (numpy.ndarray): The rotated wavefunction.
        - r_par (numpy.ndarray): The parallel coordinates.
        - r_perp_0 (numpy.ndarray): The first set of perpendicular coordinates.
        - r_perp_1 (numpy.ndarray): The second set of perpendicular coordinates.
        - axis_id (numpy.ndarray): The axis assignment.
    """
    start_time = time.time()

    # Set initial values for rotated wavefunction and real space coordinates
    psi_rot = psi.copy()
    N = psi.shape[0]
    r_par = r_perp_0 = r_perp_1 = np.linspace(0, N - 1, N)
    axis_id = np.array([0, 1, 2], dtype=int)
    
    dir_k = k_segment['dir_k']
    direction = k_segment['dir']

    print("Initial axis assignment:", axis_id)

    # Axis assignment for (100) segments
    if direction == 0:
        if abs(dir_k[1]) > 0.999999:
            axis_id = np.array([1, 0, 2], dtype=int)
        elif abs(dir_k[2]) > 0.999999:
            axis_id = np.array([2, 1, 0], dtype=int)
        print("Updated axis assignment for (100):", axis_id)
    # Rotations for (110) segments
    if direction == 1:
        angle_1 = np.degrees(k_segment['rot_angle'][0])
        angle_2 = np.degrees(k_segment['rot_angle'][1])
        print(f"Rotation angles for (110): angle_1 = {angle_1}, angle_2 = {angle_2}")

        if abs(dir_k[2]) < 1e-6:
            psi_rot = rotate(psi, angle=angle_1, axes=(0, 1), reshape=True)
            print("Rotated wavefunction around y-axis by angle_1.")
        elif abs(dir_k[1]) < 1e-6:
            psi_rot = rotate(psi, angle=angle_2, axes=(0, 2), reshape=True)
            print("Rotated wavefunction around z-axis by angle_2.")
        elif abs(dir_k[0]) < 1e-6:
            psi_i = rotate(psi, angle=angle_1, axes=(0, 1), reshape=True)
            psi_rot = rotate(psi_i, angle=angle_2, axes=(0, 2), reshape=True)
            print("Performed two rotations for (111): first by angle_1, then by angle_2.")

        # Set parallel and perpendicular coordinates
        N_par = psi_rot.shape[0]
        r_par = np.linspace(0, N_par - 1, N_par)
        N_perp_0 = psi_rot.shape[1]
        r_perp_0 = np.linspace(0, N_perp_0 - 1, N_perp_0)
        N_perp_1 = psi_rot.shape[2]
        r_perp_1 = np.linspace(0, N_perp_1 - 1, N_perp_1)

    # Set the sign of the parallel coordinate according to the direction sign
    r_par *= k_segment['r_par_sign']
    print("Adjusted parallel coordinates with direction sign.")

    end_time = time.time()
    print(f"rotate_psi executed in {end_time - start_time:.6f} seconds")

    return psi_rot, r_par, r_perp_0, r_perp_1, axis_id

def rotate_psi_111(psi, k_segment):
    """
    Orient the wavefunction in line with the given (111) direction.
    The reorientation creates a cubic grid aligned with the segment axis. The function fills in the parallel and
    perpendicular coordinates in line with the wavefunctions. Orientation of the corresponding wavenumbers
    is done upon definition of the bundle. For (111), angles are -45 and -35.2 degrees.

    Parameters:
    psi (numpy.ndarray): A 3D array representing the wavefunction.
    k_segment (dict): A dictionary containing information about the segment, including rotation angles and sign.

    Returns:
    tuple: A tuple containing the following:
        - psi_rot (numpy.ndarray): The rotated wavefunction.
        - r_par (numpy.ndarray): The parallel coordinates.
        - r_perp_0 (numpy.ndarray): The first set of perpendicular coordinates.
        - r_perp_1 (numpy.ndarray): The second set of perpendicular coordinates.
        - axis_id (numpy.ndarray): The axis assignment.
    """
    start_time = time.time()

    # Extract rotation angles and sign
    angle = k_segment['rot_angle']
    angle_1, angle_2 = np.degrees(angle[0]), np.degrees(angle[1])
    sign = k_segment['r_par_sign']
    print(f"Rotation angles: angle_1 = {angle_1}, angle_2 = {angle_2}, sign = {sign}")

    # Perform the first rotation
    psi_i = rotate(psi, angle=sign * angle_1, axes=(0, 1), reshape=True)
    print(f"Rotated wavefunction around z-axis by angle_1 ({sign * angle_1} degrees).")

    # Perform the second rotation
    psi_rot = rotate(psi_i, angle=sign * angle_2, axes=(0, 2), reshape=True)
    print(f"Rotated wavefunction around y-axis by angle_2 ({sign * angle_2} degrees).")

    # Set axis assignment
    axis_id = np.array([0, 1, 2], dtype=int)
    print(f"Axis assignment: {axis_id}")

    # Set parallel and perpendicular coordinates
    N_par = psi_rot.shape[axis_id[0]]
    r_par = np.linspace(0, N_par - 1, N_par)
    N_perp_0, N_perp_1 = psi_rot.shape[axis_id[1]], psi_rot.shape[axis_id[2]]
    r_perp_0 = np.linspace(0, N_perp_0 - 1, N_perp_0)
    r_perp_1 = np.linspace(0, N_perp_1 - 1, N_perp_1)

    # Set the sign of the parallel coordinate
    r_par *= sign
    print(f"Adjusted parallel coordinates with direction sign: {sign}")

    end_time = time.time()
    print(f"rotate_psi_111 executed in {end_time - start_time:.6f} seconds")

    return psi_rot, r_par, r_perp_0, r_perp_1, axis_id

def set_bundle_100(b, k_segment, k_structure):
    """
    Identify direction and set in-plane coordinates for a (100) bundle.
    This function initializes the in-plane coordinates based on the segment information and Nyquist limit.

    Parameters:
    b (int): Bundle index, used to determine specific coordinate adjustments.
    k_segment (dict): A dictionary containing information about the segment, including direction, position, and origin.
    k_structure (dict): A dictionary containing structural details such as the Nyquist limit.

    Returns:
    dict: A dictionary containing information about the bundle, including direction index, k-space coordinates,
          and kappa values.
    """
    start_time = time.time()

    # Identify direction and set in-plane coordinates
    dir_index = k_segment['indices']
    mask_1, mask_2 = get_masks(k_segment['dir'], dir_index)
    N = k_structure['Nyquist']
    print(f"Bundle index: {b}, Direction index: {dir_index}, Nyquist limit: {N}")

    # Create in-plane coordinates based on the bundle index (b)
    if b == 0:
        k_0_0, k_0_1 = np.linspace(-N, N, 2 * N + 1), np.linspace(-N, N, 2 * N + 1)
    else:
        k_0_0, k_0_1 = np.linspace(-N, N - 1, 2 * N), np.linspace(-N, N - 1, 2 * N)
    print(f"In-plane coordinates (k_0_0, k_0_1) created for bundle {b}.")

    # Calculate k_0 perpendicular coordinates
    k_0 = k_segment['pos_k']
    k_0_perp = np.array([np.dot(mask_1, k_0), np.dot(mask_2, k_0)])
    print(f"k_0 perpendicular coordinates: {k_0_perp}")

    # Create array with k0 coordinates of the bundle
    k0_origin = k_segment['origin_bun'][b]
    k0_origin_perp = np.array([np.dot(mask_1, k0_origin), np.dot(mask_2, k0_origin)])
    k_0_0 += k0_origin_perp[0] + k_0_perp[0]
    k_0_1 += k0_origin_perp[1] + k_0_perp[1]
    print(f"Adjusted in-plane coordinates for bundle {b}: k_0_0 and k_0_1.")

    # Set kappa array
    N_k = k_segment['kappa'].size
    dk = k_segment['dk']
    print(f"Number of kappa points (N_k): {N_k}, dk: {dk}")

    # Initialize kappa array for the bundle
    if b == 0:
        kappa = np.zeros((N_k, 2 * N + 1))
        for i in range(2 * N + 1):
            N_zone = -N + i
            kappa_1 = k_segment['kappa_12'][0] + N_zone
            kappa_2 = k_segment['kappa_12'][1] + N_zone
            kappa[:, i] = np.linspace(kappa_1, kappa_2 - dk, N_k)
#            print(f"kappa values for bundle {b}, zone {N_zone}: {kappa[:, i]}")
    else:
        kappa = np.zeros((N_k, 2 * N))
        for i in range(2 * N):
            N_zone = -N + 0.5 + i
            kappa_1 = k_segment['kappa_12'][0] + N_zone
            kappa_2 = k_segment['kappa_12'][1] + N_zone
            kappa[:, i] = np.linspace(kappa_1, kappa_2 - dk, N_k)
#            print(f"kappa values for bundle {b}, zone {N_zone}: {kappa[:, i]}")

    # Create the bundle dictionary
    bundle = {
        'dir_index': dir_index,
        'k_0_0': k_0_0,
        'k_0_1': k_0_1,
        'kappa': kappa,
        'psi_proj': np.array([])
    }

    end_time = time.time()
    print(f"set_bundle_100 executed in {end_time - start_time:.6f} seconds")

    return bundle

def combinations_110_bis(k_segment, l, b, Nyq):
    """
    Generate combinations for a (110) bis direction in reciprocal space.

    Parameters:
    k_segment (dict): A dictionary containing information about the k-path segment, such as direction and origin.
    l (int): The level for the (110) direction.
    b (int): Bundle index.
    Nyq (int): Nyquist limit for the wave vector.

    Returns:
    numpy.ndarray: A 2D array representing the combinations for the (110) bis direction.
    """
    start_time = time.time()

    # Extract sign and calculate the direction index
    sign = k_segment['r_par_sign']
    index = sign * k_segment['indices']
    print(f"Sign: {sign}, Direction indices: {index}")

    # Generate n_2 values for the BZ structure
    n_2 = np.linspace(-Nyq, Nyq - b, 2 * Nyq + 1 - b)
    print(f"n_2 values: {n_2}")

    # Create BZ_2D structure based on l value
    if l == 0:
        BZ_2D = np.array([[0, 0]])
    else:
        BZ_2D = np.array([[l, 0], [0, l]])
    print(f"BZ_2D structure: {BZ_2D}")

    # Determine position indices for y and z based on direction index
    pos_y, pos_z = 1, 2
    if abs(index[1]) < 1e-6:
        pos_y, pos_z = 2, 1
    elif abs(index[0]) < 1e-6:
        pos_y, pos_z = 2, 0
    print(f"Position indices - pos_y: {pos_y}, pos_z: {pos_z}")

    # Efficiently repeat and tile arrays for BZ calculation
    repeat_BZ_2D = np.repeat(BZ_2D, n_2.shape[0], axis=0)
    tiled_n_2 = np.tile(n_2, len(BZ_2D)).reshape(-1, 1)

    # Construct the final BZ array
    BZ = np.hstack((repeat_BZ_2D[:, :pos_z], tiled_n_2, repeat_BZ_2D[:, pos_z:]))
    BZ[:, pos_y] *= index[pos_y]
    BZ += k_segment['origin_bun'][b]
    print(f"Final BZ array: {BZ}")

    end_time = time.time()
    print(f"combinations_110_bis executed in {end_time - start_time:.6f} seconds")

    return BZ

def set_bundle_110(BZ, l, b, k_segment, k_structure):
    """
    Identify direction and set in-plane coordinates for a (110) bundle.
    This function initializes the in-plane coordinates based on the BZ, segment information, and Nyquist limit.

    Parameters:
    BZ (numpy.ndarray): Array representing the Brillouin Zone.
    l (int): Level parameter for determining kappa range.
    b (int): Bundle index, used to determine specific coordinate adjustments.
    k_segment (dict): A dictionary containing information about the segment, including direction, position, and basis.
    k_structure (dict): A dictionary containing structural details such as the Nyquist limit.

    Returns:
    dict: A dictionary containing information about the bundle, including direction index, k-space coordinates,
          and kappa values.
    """
    start_time = time.time()

    # Identify direction and set in-plane coordinates
    dir_index = k_segment['indices']
    mask_1, mask_2 = get_masks(k_segment['dir'], dir_index)
    N = k_structure['Nyquist']
    basis = k_segment['k_perp_basis']
    print(f"Bundle index: {b}, Direction index: {dir_index}, Nyquist limit: {N}")

    # Create array with k0 coordinates of the layer in the bundle
    e_par = basis[0]
    e_perp_0, e_perp_1 = basis[1], basis[2]
    print(f"Basis vectors - e_par: {e_par}, e_perp_0: {e_perp_0}, e_perp_1: {e_perp_1}")

    # Calculate k_perp_0 and k_perp_1
    k_perp_0 = np.sum(BZ * e_perp_0, axis=1)
    k_perp_1 = np.sum(BZ * e_perp_1, axis=1)
    k_0 = k_segment['pos_k']
    k_perp_0 += np.dot(e_perp_0, k_0)
    k_perp_1 += np.dot(e_perp_1, k_0)
    print(f"k_perp_0: {k_perp_0}, k_perp_1: {k_perp_1}")
    # Set kappa array
    N_k = k_segment['kappa'].size
    dk = k_segment['dk']
    n_min = l - 2 * N
    n_max = 2 * (N - b) - l
    n_kappa = round((n_max - n_min) / 2 + 1)
    print(f"Number of kappa points (N_k): {N_k}, dk: {dk}, n_min: {n_min}, n_max: {n_max}, n_kappa: {n_kappa}")

    # Initialize kappa array for the bundle
    kappa = np.zeros((N_k, n_kappa))
    kappa_0 = np.dot(e_par, k_segment['origin_bun'][b])
    for i in range(n_kappa):
        N_zone = n_min / 2 + i
        kappa_1 = kappa_0 + k_segment['kappa_12'][0] + N_zone / k_segment['scale']
        kappa_2 = kappa_0 + k_segment['kappa_12'][1] + N_zone / k_segment['scale']
        kappa[:, i] = np.linspace(kappa_1, kappa_2 - dk, N_k)
#        print(f"kappa values for bundle {b}, zone {N_zone}: {kappa[:, i]}")

    # Create the bundle dictionary
    bundle = {
        'dir_index': dir_index,
        'k_0_0': k_perp_0,
        'k_0_1': k_perp_1,
        'kappa': kappa,
        'psi_proj': np.array([])
    }

    end_time = time.time()
    print(f"set_bundle_110 executed in {end_time - start_time:.6f} seconds")

    return bundle

def combinations_111(width, length, bundle, k_segment):
    """
    Generates combinations of unit cell translations for the (111) crystallographic direction 
    based on the given width, length, and bundle parameters. Adjusts directions based on 
    signs and indices in the k-segment.

    Parameters:
    - width: int, width of the translation in reciprocal space.
    - length: int, length of the translation in reciprocal space.
    - bundle: int, index of the bundle being processed.
    - k_segment: dict, contains parameters for the current k-segment, including:
        - 'r_par_sign': array-like, signs for parallel directions.
        - 'indices': array-like, indices for each axis.
        - 'origin_bun': array-like, origin points for the bundle.

    Returns:
    - BZ: 2D numpy array, containing combinations of cell translations in reciprocal space.
    """

    start_time = time.time()
    print(f"Starting combinations_111 with width={width}, length={length}, bundle={bundle}")

    # Retrieve parameters from k_segment
    sign = k_segment['r_par_sign']
    index = sign * k_segment['indices']

    # Generate permutations of the cell translations
    cell = [width, length, 0]
    all_cells = set(permutations(cell))  # Unique permutations
    all_cells_array = np.array(list(all_cells))

    print("Generated initial cell permutations.")
    
    # Adjust cells based on index sign conditions
    if np.sum(index) < 1.00001:
        if index[0] > 0.99999 and index[1] > 0.99999:
            all_cells_array[:, 2] *= -1
        elif index[0] > 0.99999 and index[2] > 0.99999:
            all_cells_array[:, 1] *= -1
        elif np.sum(index) < -0.99999:
            all_cells_array[:, 1] *= -1
            all_cells_array[:, 2] *= -1

    # Convert to float and add origin point for the bundle
    BZ = all_cells_array.astype(float)
    BZ += k_segment['origin_bun'][bundle]

    print(f"combinations_111 completed in {time.time() - start_time:.4f} seconds")
    return BZ


def set_bundle_111(BZ, w, l, b, k_segment, k_structure):
    """
    Identify direction and set in-plane coordinates for a (111) bundle.
    This function initializes the in-plane coordinates based on the BZ, segment information, and Nyquist limit.

    Parameters:
    BZ (numpy.ndarray): Array representing the Brillouin Zone.
    w (int): Width parameter for determining kappa range.
    l (int): Length parameter for determining kappa range.
    b (int): Bundle index, used to determine specific coordinate adjustments.
    k_segment (dict): A dictionary containing information about the segment, including direction, position, and basis.
    k_structure (dict): A dictionary containing structural details such as the Nyquist limit.

    Returns:
    dict: A dictionary containing information about the bundle, including direction index, k-space coordinates,
          and kappa values.
    """
    start_time = time.time()

    # Identify direction and set in-plane coordinates
    dir_index = k_segment['indices']
    mask_1, mask_2 = get_masks(k_segment['dir'], dir_index)
    N = k_structure['Nyquist']
    basis = k_segment['k_perp_basis']
    print(f"Bundle index: {b}, Direction index: {dir_index}, Nyquist limit: {N}")

    # Create array with k0 coordinates of the layer in the bundle
    e_par = basis[0]
    e_perp_0, e_perp_1 = basis[1], basis[2]
    k_0 = k_segment['pos_k']

    # Use np.dot for optimized multiplication
    k_perp_0 = np.dot(BZ, e_perp_0) + np.dot(e_perp_0, k_0)
    k_perp_1 = np.dot(BZ, e_perp_1) + np.dot(e_perp_1, k_0)
    print(f"k_perp_0: {k_perp_0}, k_perp_1: {k_perp_1}")

    # Set kappa array using vectorized calculations
    N_k = k_segment['kappa'].size
    dk = k_segment['dk']
    n_min = w + l - 3 * N
    n_max = 3 * (N - b) + l - 2 * w
    n_kappa = round((n_max - n_min) / 3 + 1)
    print(f"Number of kappa points (N_k): {N_k}, dk: {dk}, n_min: {n_min}, n_max: {n_max}, n_kappa: {n_kappa}")

    # Initialize kappa array for the bundle
    kappa = np.zeros((N_k, n_kappa))
    kappa_0 = np.dot(e_par, k_segment['origin_bun'][b])
    for i in range(n_kappa):
        n_cell = n_min + 3 * i
        kappa_1 = kappa_0 + k_segment['kappa_12'][0] + n_cell * k_segment['scale']
        kappa_2 = kappa_0 + k_segment['kappa_12'][1] + n_cell * k_segment['scale']
        kappa[:, i] = np.linspace(kappa_1, kappa_2 - dk, N_k)
#        print(f"kappa values for bundle {b}, cell {n_cell}: {kappa[:, i]}")

    # Create the bundle dictionary
    bundle = {
        'dir_index': dir_index,
        'k_0_0': k_perp_0,
        'k_0_1': k_perp_1,
        'kappa': kappa,
        'psi_proj': np.array([])
    }

    end_time = time.time()
    print("set_bundle_111 executed in {:.6f} seconds".format(end_time - start_time))

    return bundle

def get_masks(direction, dir_index):
    """
    Provides the conversion of the coordinates of the position vector k_0 before rotation of the wavefunction
    into the (in-plane) coordinates after rotation. Axes are swapped to mimic a rotation for specific directions.

    Parameters:
    direction (int): Direction identifier (0 for (100), 1 for (110), 2 for (111)).
    dir_index (array-like): Direction indices for the segment.

    Returns:
    tuple: mask_1, mask_2 (numpy.ndarray) representing the conversion masks.
    """
    start_time = time.time()
    print(f"Calculating masks for direction: {direction}, dir_index: {dir_index}")

    mask_1, mask_2 = np.array([0, 1, 0]), np.array([0, 0, 1])  # Default masks for (100) direction

    if direction == 0:
        if abs(dir_index[1]) == 1:
            mask_1, mask_2 = np.array([1, 0, 0]), np.array([0, 0, 1])  # Masks for (010) direction
        elif abs(dir_index[2]) == 1:
            mask_1, mask_2 = np.array([0, 1, 0]), np.array([1, 0, 0])  # Masks for (001) direction
    elif direction == 1:
        mask_1 = np.array([-1 / np.sqrt(2), 1 / np.sqrt(2), 0])  # Masks for (110) direction
        mask_2 = np.array([0, 0, 1])
        if abs(dir_index[2]) == 0 and (dir_index[0] + dir_index[1]) == 0:
            mask_1 = np.array([1 / np.sqrt(2), 1 / np.sqrt(2), 0])  # Masks for (-110) direction
        elif abs(dir_index[1]) == 0:
            mask_1 = np.array([-1 / np.sqrt(2), 0, 1 / np.sqrt(2)])  # Masks for (101) direction
            mask_2 = np.array([0, 1, 0])
            if (dir_index[0] + dir_index[2]) == 0:
                mask_1 = np.array([1 / np.sqrt(2), 0, 1 / np.sqrt(2)])  # Masks for (-101)
        elif abs(dir_index[0]) == 0:
            mask_1 = np.array([0, -1 / np.sqrt(2), 1 / np.sqrt(2)])  # Masks for (011) direction
            mask_2 = np.array([1, 0, 0])
            if (dir_index[1] + dir_index[2]) == 0:
                mask_1 = np.array([0, 1 / np.sqrt(2), -1 / np.sqrt(2)])
    elif direction == 2:
        mask_1 = np.array([-1 / np.sqrt(2), 1 / np.sqrt(2), 0])  # Masks for (111) direction
        mask_2 = np.array([-1 / np.sqrt(6), -1 / np.sqrt(6), 2 / np.sqrt(6)])

    end_time = time.time()
    print("get_masks executed in {:.6f} seconds".format(end_time - start_time))

    return mask_1, mask_2

def closest(x):
    """
    Find the closest integer to a given value.

    Parameters:
    x (float): The value to round.

    Returns:
    int: The closest integer to the input value.
    """
    start_time = time.time()
    result = int(np.round(x))  # Use numpy for efficient rounding
    end_time = time.time()
    print("closest executed in {:.6f} seconds".format(end_time - start_time))
    return result


def find_closest_index(r_range, r):
    """
    Find the index of the closest value in an array to a given value.

    Parameters:
    r_range (numpy.ndarray): The array of values to search.
    r (float): The target value.

    Returns:
    int: The index of the closest value in the array.
    """
    start_time = time.time()
    closest_index = int(np.argmin(np.abs(r_range - r)))  # Use numpy for efficient array operations
    end_time = time.time()
    print("find_closest_index executed in {:.6f} seconds".format(end_time - start_time))
    return closest_index

def organize_output_path(k_path, k_path_points):
    """
    Generates a predefined path through reciprocal space by concatenating different segments.
    
    Parameters:
    - k_path: list of dictionaries, where each dictionary represents a segment with keys 'dk' (step in k-space) 
      and 'kappa' (array of kappa points for the segment).
    - k_path_points: array-like, points that define the segments in reciprocal space.

    Returns:
    - kappa: numpy array, concatenated array of kappa points through all segments.
    - kappa_ticks: numpy array, positions of high-symmetry points defining the start and end of each segment.
    """
    
    start_time = time.time()
    print("Starting organize_output_path function...")
    
    N_segment = len(k_path_points) - 1  # Number of segments
    kappa = [0]                         # Initialize kappa array with the starting point
    kappa_ticks = np.zeros(N_segment + 1)  # Array to store tick positions for each segment
    kappa_end = 0

    # Iterate over each segment to concatenate kappa points
    for s in range(N_segment):
        segment = k_path[s]
        dkappa_s = segment['dk']
        kappa_s = np.array(segment['kappa'], copy=True)
        
        # Adjust kappa_s for continuity with the end of previous segment
        kappa_s -= (kappa_s[0] - kappa_end)
        
        # Concatenate current segment kappa points
        kappa.extend(kappa_s)
        
        # Update end of the segment and tick position
        kappa_end = kappa_s[-1] + dkappa_s
        kappa_ticks[s + 1] = kappa_end

    # Add the final point to close the path
    kappa.append(kappa_end)

    # Convert kappa to a numpy array and skip the first initial placeholder zero
    kappa = np.array(kappa[1:])
    
    # Timing and completion message
    end_time = time.time()
    print(f"organize_output_path completed in {end_time - start_time:.4f} seconds")
    print(f"Generated kappa path with {len(kappa)} points and {len(kappa_ticks)} tick marks.")

    return kappa, kappa_ticks

def organize_output_phi(k_path):
    """
    Merges all projected phi densities across segments along a predefined path through reciprocal space.
    
    Parameters:
    - k_path: list of dictionaries, where each dictionary represents a segment with a key 'phi_folded'
      containing the expansion coefficients for that segment.

    Returns:
    - phi_folded: numpy array, 1D array of expansion coefficients folded along the kappa axis in BZ1.
    """

    start_time = time.time()
    print("Starting organize_output_phi function...")

    N_segment = len(k_path)  # Number of segments
    phi_folded = []  # Using a list for efficient concatenation

    # Concatenate all phi_folded segments
    for s in range(N_segment):
        segment = k_path[s]
        phi_folded_segment = segment['phi_folded']
        phi_folded.extend(phi_folded_segment)
    
    # Set info in the first and last points to be equal
    phi_folded.append(phi_folded[0])

    # Convert the list to a numpy array
    phi_folded = np.array(phi_folded)

    # Timing and completion message
    end_time = time.time()
    print(f"organize_output_phi completed in {end_time - start_time:.4f} seconds")
    print(f"Generated phi_folded array with {len(phi_folded)} elements.")

    return phi_folded


"""
def clip_array(array, n_min, n_max):
    clips array using a border defined by n_min and n_max -- removing elements along all dimensions
    before position n_min and after position n_max

    # Get the shape of the array
    shape = array.shape
    # Create a mask for each dimension
    mask_axis0 = (np.arange(shape[0]) >= n_min) & (np.arange(shape[0]) <= n_max)
    mask_axis1 = (np.arange(shape[1]) >= n_min) & (np.arange(shape[1]) <= n_max)
    mask_axis2 = (np.arange(shape[2]) >= n_min) & (np.arange(shape[2]) <= n_max)
    # Apply the masks to the array
    clipped_array = array[mask_axis0][:, mask_axis1][:, :, mask_axis2]

    return clipped_array
"""
import numpy as np
import time

def clip_cube(psi, atom_pos, frame, dx):
    """
    Clips the 3D array `psi` around the outermost atoms with a specified frame width.
    
    Parameters:
    - psi: 3D numpy array, the data to be clipped.
    - atom_pos: list or array of atomic positions, each entry containing (x, y, z) coordinates.
    - frame: float, the extra border width to include around the atoms.
    - dx: float, the spatial resolution of `psi` (distance per array element).
    
    Returns:
    - psi_clipped: 3D numpy array, clipped version of `psi` including a border around the outermost atoms.
    """
    
    start_time = time.time()
    print("Starting clip_cube function...")

    # Convert atomic positions to numpy array for easier slicing
    atom_pos_array = np.array(atom_pos)
    
    # Get minimum and maximum atom position along x, y, z directions
    min_pos = np.min(atom_pos_array, axis=0)  # [x_min, y_min, z_min]
    max_pos = np.max(atom_pos_array, axis=0)  # [x_max, y_max, z_max]
    
    # Calculate array index range based on atom positions and frame
    n_min = np.floor(min_pos / dx - frame / dx).astype(int)
    n_max = np.ceil(max_pos / dx + frame / dx).astype(int)
    
    # Clip the array within calculated bounds, ensuring bounds are valid
    psi_clipped = psi[
        max(n_min[0], 0): min(n_max[0], psi.shape[0]),
        max(n_min[1], 0): min(n_max[1], psi.shape[1]),
        max(n_min[2], 0): min(n_max[2], psi.shape[2])
    ]

    # Timing and completion message
    end_time = time.time()
    print(f"clip_cube completed in {end_time - start_time:.4f} seconds")
    print(f"Clipped psi to shape {psi_clipped.shape} with bounds in each dimension adjusted by frame.")

    return psi_clipped

def bse_cube(file_specifiers, log_file, k_path, kappa_path, data):
    """
    Processes multiple cube files, applies BSE analysis, and returns folded states and processed states.
    
    Parameters:
    - file_specifiers: dict, contains information about file naming and configuration.
      Required keys: 'N_cube', 'cube_0', 'Project', 'State', 'WFN', 'Addition', 'extension'.
    - log_file: file-like object or path, used to log processing information.
    - k_path: array-like, path through reciprocal space for BSE analysis.
    - kappa_path: array-like, wavenumber data for processing.
    - data: dict, configuration parameters (e.g., frame width, clip flag).
      Required keys: 'frame', 'clip'.
    
    Returns:
    - bse_folded_states: numpy array, results of BSE analysis for each cube file processed.
    - state_nr: numpy array, cube state numbers successfully processed.
    - files_processed: bool, indicates if any files were processed successfully.
    """
    
    start_time = time.time()
    print("Starting bse_cube function...")
    
    no_error = True
    files_processed = False
    N_data = len(kappa_path)
    bse_folded_states = []  # Using a list to gather results before converting to numpy array
    state_nr = []  # List to track successfully processed cube state numbers
    
    N_cube = file_specifiers['N_cube']
    cube_0 = file_specifiers['cube_0']
    frame = data['frame']
    clip = data['clip']
    
    for cube in range(N_cube):
        cube_i = cube_0 + cube
        log_output(f"state {cube_i} started", log_file)
        
        file_name = (
            f"{file_specifiers['Project']}_{file_specifiers['State']}{file_specifiers['WFN']}"
            f"{cube_i}{file_specifiers['Addition']}.{file_specifiers['extension'][0]}"
        )
        log_output(f"try open {file_name}", log_file)
        
        # Attempt to read the cube file
        psi, meta, atom_Z, atom_pos, no_error = read_cube(file_name)
        
        if no_error:
            log_output("cube file loaded", log_file)
            data['dx'] = meta['xvec'][0]
            
            # Apply clipping if specified
            if clip:
                psi = clip_cube(psi, atom_pos, frame, data['dx'])
            
            # Perform BSE analysis and append results
            phi_folded_path = bse(psi, k_path, data, log_file)
            bse_folded_states.append(phi_folded_path)
            state_nr.append(cube_i)
            log_output(f"state {cube_i} analyzed", log_file)
            files_processed = True
        else:
            log_output(f"ERROR - state {cube_i}, analysis skipped", log_file)
            continue

    # Convert lists to numpy arrays if files were processed
    if files_processed:
        bse_folded_states = np.vstack(bse_folded_states)
        state_nr = np.array(state_nr)
    else:
        bse_folded_states = np.empty((0, N_data))  # Empty array if no files were processed
        state_nr = np.empty((0,), dtype=int)

    # Timing and completion message
    end_time = time.time()
    print(f"bse_cube completed in {end_time - start_time:.4f} seconds")
    print(f"Processed {len(state_nr)} cube files successfully.")

    return bse_folded_states, state_nr, files_processed

def bse_h5(file_specifiers, log_file, k_path, kappa_path, data):
    """
    Processes an HDF5 file containing multiple states, applies BSE analysis, and returns folded states and state numbers.
    
    Parameters:
    - file_specifiers: dict, contains information about file naming and configuration.
      Required keys: 'cube_0', 'h5_file', 'extension'.
    - log_file: file-like object or path, used to log processing information.
    - k_path: array-like, path through reciprocal space for BSE analysis.
    - kappa_path: array-like, wavenumber data for processing.
    - data: dict, configuration parameters (e.g., frame width, clip flag).
      Required keys: 'clip', 'frame'.
    
    Returns:
    - bse_folded_states: numpy array, results of BSE analysis for each state in the HDF5 file.
    - state_nr: numpy array, state numbers successfully processed.
    - files_processed: bool, indicates if any states were processed successfully.
    """
    
    start_time = time.time()
    print("Starting bse_h5 function...")

    no_error = True
    files_processed = False
    N_data = len(kappa_path)
    bse_folded_states = []  # Using a list for efficient accumulation before final array conversion
    state_nr = []  # List to track successfully processed state numbers
    
    clip = data['clip']
    frame = data['frame']
    state_0 = file_specifiers['cube_0']
    h5_file = f"{file_specifiers['h5_file']}.{file_specifiers['extension'][1]}"
    
    # Attempt to load the HDF5 file
    log_output(f"search for {h5_file}", log_file)
    try:
        with h5py.File(h5_file, 'r') as h5:
            psi_all = h5['psi_r'][:]
            atom_pos = h5['atoms'][:]
            dr = h5['grid_spacing'][:]
            print(f"Grid spacing (dr): {dr}")
            data['dx'] = dr[0]
    except FileNotFoundError:
        no_error = False
        log_output(f"{h5_file} not found", log_file)
    
    if no_error:
        log_output("h5 file loaded", log_file)
        N_states = psi_all.shape[0]  # Number of states in the file
        
        # Process each state in the HDF5 file
        for state in range(N_states):
            psi = psi_all[state]
            
            # Clip psi if clipping is enabled
            if clip:
                psi = clip_cube(psi, atom_pos, frame, data['dx'])
            
            # Perform BSE analysis and store results
            phi_folded_path = bse(psi, k_path, data, log_file)
            bse_folded_states.append(phi_folded_path)
            state_nr.append(state + state_0)
            log_output(f"state {state} analyzed", log_file)
            files_processed = True
    else:
        log_output("ERROR - BSE analysis stopped", log_file)
    
    # Convert lists to numpy arrays if any states were processed
    if files_processed:
        bse_folded_states = np.vstack(bse_folded_states)
        state_nr = np.array(state_nr)
    else:
        bse_folded_states = np.empty((0, N_data))  # Empty array if no states were processed
        state_nr = np.empty((0,), dtype=int)

    # Timing and completion message
    end_time = time.time()
    print(f"bse_h5 completed in {end_time - start_time:.4f} seconds")
    print(f"Processed {len(state_nr)} states successfully.")

    return bse_folded_states, state_nr, files_processed

def chunked_iterable(iterable, chunk_size):
    """Yield successive chunks from an iterable."""
    for i in range(0, len(iterable), chunk_size):
        yield iterable[i:i + chunk_size]

def process_bundle_chunk_100(chunk, k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx):
    """Processes a chunk of bundles for 100 segments and returns their combined result."""
    phi_folded_chunk = np.zeros(k_segment['phi_folded'].shape)
    for b in chunk:
        bundle = set_bundle_100(b, k_segment, k_structure)
        k0_perp_0, k0_perp_1 = bundle['k_0_0'], bundle['k_0_1']
        k00_x_rp0 = np.outer(k0_perp_0, r_perp_0) * k_unit * dx
        k01_x_rp1 = np.outer(k0_perp_1, r_perp_1) * k_unit * dx
        factor_perp = np.exp(-1j * (k00_x_rp0[:, :, None, None] + k01_x_rp1[None, None, :, :]))
        psi_projection_unfolded = np.tensordot(factor_perp, psi_rot, axes=([1, 3], [axis_id[1], axis_id[2]]))
        kappa = bundle['kappa']
        factor_par = np.exp(-1j * (k_unit * kappa[:, :, None] * r_par[None, None, :]) * dx)
        phi_projection_unfolded = np.tensordot(factor_par, psi_projection_unfolded, axes=([2], [2]))
        phi_folded_chunk += np.sum(abs(phi_projection_unfolded) ** 2, axis=(1, 2, 3))
    return phi_folded_chunk

def process_bundle_chunk_110(chunk, k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx, Nyq):
    """Processes a chunk of bundles for 110 segments and returns their combined result."""
    phi_folded_chunk = np.zeros(k_segment['phi_folded'].shape)
    for b, l in chunk:
        BZ = combinations_110_bis(k_segment, l, b, Nyq)
        bundle = set_bundle_110(BZ, l, b, k_segment, k_structure)
        k0_perp_0, k0_perp_1 = bundle['k_0_0'], bundle['k_0_1']
        factor_perp = np.exp(-1j * (
            (k0_perp_0[:, None, None] * r_perp_0[None, :, None] +
             k0_perp_1[:, None, None] * r_perp_1[None, None, :]) * k_unit * dx))
        psi_projection_unfolded = np.tensordot(factor_perp, psi_rot, axes=([1, 2], [axis_id[1], axis_id[2]]))
        kappa = bundle['kappa']
        factor_par = np.exp(-1j * (k_unit * kappa[:, :, None] * r_par[None, None, :]) * dx)
        phi_projection_unfolded = np.tensordot(factor_par, psi_projection_unfolded, axes=([2], [1]))
        phi_folded_chunk += np.sum(abs(phi_projection_unfolded) ** 2, axis=(1, 2))
    return phi_folded_chunk

def process_bundle_chunk_111(chunk, k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx):
    """Processes a chunk of bundles for 111 segments and returns their combined result."""
    phi_folded_chunk = np.zeros(k_segment['phi_folded'].shape)
    for b, w, l in chunk:
        BZ = combinations_111(w, l, b, k_segment)
        bundle = set_bundle_111(BZ, w, l, b, k_segment, k_structure)
        k0_perp_0, k0_perp_1 = bundle['k_0_0'], bundle['k_0_1']
        factor_perp = np.exp(-1j * (
            (k0_perp_0[:, None, None] * r_perp_0[None, :, None] +
             k0_perp_1[:, None, None] * r_perp_1[None, None, :]) * k_unit * dx))
        psi_projection_unfolded = np.tensordot(factor_perp, psi_rot, axes=([1, 2], [axis_id[1], axis_id[2]]))
        kappa = bundle['kappa']
        factor_par = np.exp(-1j * (k_unit * kappa[:, :, None] * r_par[None, None, :]) * dx)
        phi_projection_unfolded = np.tensordot(factor_par, psi_projection_unfolded, axes=([2], [1]))
        phi_folded_chunk += np.sum(abs(phi_projection_unfolded) ** 2, axis=(1, 2))
    return phi_folded_chunk

def bse(psi, k_path, data, log_file):
    """
    Performs Band Structure Expansion (BSE) analysis on a wavefunction along a pre-defined k-path.

    Parameters:
    - psi: 3D numpy array, the wavefunction data to be analyzed.
    - k_path: list of dicts, each containing data on specific k-path segments.
    - data: dict, containing required parameters such as lattice parameter 'latt_par', spacing 'dx', and 'k_unit'.

    Returns:
    - phi_folded_path: 1D numpy array, folded expansion coefficients for all segments in k_path.
    """

    start_time = time.time()
    log_output("Starting BSE analysis...", log_file)

    # Get calculation data
    a = data['latt_par']
    dx = data['dx']
    k_unit = data['k_unit']
    
    # Prepare for BSE along pre-defined path    
    segments = len(k_path)
    k_structure = summary_k_path(k_path, segments, a / dx)
    Nyq = k_structure['Nyquist']
    n_100, n_110, n_111 = k_structure['n_dir']

    # Check if running within a Slurm environment and use SLURM_CPUS_PER_TASK if available, otherwise use os.cpu_count()
    n_cores = int(os.environ.get('SLURM_CPUS_PER_TASK', os.cpu_count()))
    os.environ["OMP_NUM_THREADS"] = str(n_cores)

    log_output(f"Number of CPUs : {n_cores}", log_file)
    chunk_multiplier = 1  # Adjusted to prevent excessive parallel overhead when cores are large
    log_output(f"Chunk multiplier : {chunk_multiplier}", log_file)

    # Expansion for the 100 segments
    for segment in range(n_100):
        segment_start = time.time()
        pos_100 = int(k_structure['pos_dir'][0, segment])
        k_segment = k_path[pos_100]
        k_segment['phi_folded'][:] = 0
        bundles = k_segment['N_bun']
        psi_rot, r_par, r_perp_0, r_perp_1, axis_id = rotate_psi(psi, k_segment)

        # Calculate the number of tensordot operations for the 100 segment
        num_tensordot_operations = bundles
        log_output(f"Segment {segment} (100) - Number of tensordot operations: {num_tensordot_operations}", log_file)

        # Determine cores to use based on the number of operations
        cores_to_use = min(n_cores, num_tensordot_operations)
        log_output(f"Segment {segment} (100) - Using {cores_to_use} cores", log_file)

        chunk_size = max(1, num_tensordot_operations // cores_to_use)
        chunked_bundles = list(chunked_iterable(range(bundles), chunk_size))

        # Process chunks in parallel if applicable
        if num_tensordot_operations > 1:
            results = Parallel(n_jobs=cores_to_use)(
                delayed(process_bundle_chunk_100)(
                    chunk, k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx
                )
                for chunk in chunked_bundles
            )

            for phi_folded in results:
                k_segment['phi_folded'] += phi_folded
        else:
            for b in range(bundles):
                k_segment['phi_folded'] += process_bundle_chunk_100(
                    [b], k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx
                )

        log_output(f"Segment {segment} (100) processed in {time.time() - segment_start:.4f} seconds", log_file)
    log_output(f"{n_100} 100 segments processed", log_file)

    # Expansion for the 110 segments
    for segment in range(n_110):
        segment_start = time.time()
        pos_110 = int(k_structure['pos_dir'][1, segment])
        k_segment = k_path[pos_110]
        k_segment['phi_folded'][:] = 0
        bundles = k_segment['N_bun']
        psi_rot, r_par, r_perp_0, r_perp_1, axis_id = rotate_psi(psi, k_segment)

        # Calculate total tensordot operations for the 110 segment
        tensordot_operations = [(b, l) for b in range(bundles) for l in range(2 * Nyq + 1 - b)]
        num_tensordot_operations = len(tensordot_operations)
        log_output(f"Segment {segment} (110) - Number of tensordot operations: {num_tensordot_operations}", log_file)

        # Determine cores to use based on the number of operations
        cores_to_use = min(n_cores, num_tensordot_operations)
        log_output(f"Segment {segment} (110) - Using {cores_to_use} cores", log_file)

        chunk_size = max(1, num_tensordot_operations // cores_to_use)
        chunked_operations = [tensordot_operations[i:i + chunk_size] for i in range(0, num_tensordot_operations, chunk_size)]

        # Process chunks in parallel if applicable
        if num_tensordot_operations > 1:
            results = Parallel(n_jobs=cores_to_use)(
                delayed(process_bundle_chunk_110)(
                    chunk, k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx, Nyq
                )
                for chunk in chunked_operations
            )

            # Sum the results from each chunk
            for phi_folded in results:
                k_segment['phi_folded'] += phi_folded
        else:
            for b, l in tensordot_operations:
                k_segment['phi_folded'] += process_bundle_chunk_110(
                    [(b, l)], k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx, Nyq
                )

        log_output(f"Segment {segment} (110) processed in {time.time() - segment_start:.4f} seconds", log_file)
    log_output(f"{n_110} 110 segments processed", log_file)

    # Expansion for the 111 segments
    for segment in range(n_111):
        segment_start = time.time()
        pos_111 = int(k_structure['pos_dir'][2, segment])
        k_segment = k_path[pos_111]
        k_segment['phi_folded'][:] = 0
        bundles = k_segment['N_bun']
        psi_rot, r_par, r_perp_0, r_perp_1, axis_id = rotate_psi_111(psi, k_segment)

        # Calculate total tensordot operations for the 111 segment
        bundle_width_layer_combinations = [
            (b, w, l) for b in range(bundles)
            for w in range(2 * Nyq + 1 - b)
            for l in range(w + 1)
        ]
        num_tensordot_operations = len(bundle_width_layer_combinations)
        log_output(f"Segment {segment} (111) - Number of tensordot operations: {num_tensordot_operations}", log_file)

        # Determine cores to use based on the number of operations
        cores_to_use = min(n_cores, num_tensordot_operations)
        log_output(f"Segment {segment} (111) - Using {cores_to_use} cores", log_file)

        chunk_size = max(1, num_tensordot_operations // cores_to_use)
        chunked_combinations = [bundle_width_layer_combinations[i:i + chunk_size]
                                for i in range(0, num_tensordot_operations, chunk_size)]

        # Process chunks in parallel if applicable
        results = Parallel(n_jobs=cores_to_use)(
            delayed(process_bundle_chunk_111)(
                chunk, k_segment, k_structure, psi_rot, r_par, r_perp_0, r_perp_1, axis_id, k_unit, dx
            )
            for chunk in chunked_combinations
        )

        # Sum the results from each chunk
        for phi_folded in results:
            k_segment['phi_folded'] += phi_folded

        log_output(f"Segment {segment} (111) processed in {time.time() - segment_start:.4f} seconds", log_file)
    log_output(f"{n_111} 111 segments processed", log_file)

    # Organize and transfer the results to a single 1D array
    log_output("Organizing folded path results...", log_file)
    phi_folded_path = organize_output_phi(k_path)
    log_output(f"BSE analysis completed in {time.time() - start_time:.4f} seconds.", log_file)

    return phi_folded_path

def write_path(project, k_path_names, kappa_ticks, kappa):
    """
    Writes the k-path information to a pickle file for later use.

    Parameters:
    - project: str, base name of the project used to name the output file.
    - k_path_names: list, names of high-symmetry points along the k-path.
    - kappa_ticks: array-like, positions of k-path ticks corresponding to high-symmetry points.
    - kappa: array-like, array of wavenumbers along the k-path.

    Returns:
    - None
    """

    start_time = time.time()
    fname = f"{project}_bse_k_path.pkl"
    print(f"Writing k-path to file: {fname}")

    with open(fname, "wb") as f:
        pickle.dump((k_path_names, kappa_ticks, kappa), f)

    print(f"k-path data written to {fname} in {time.time() - start_time:.4f} seconds")

def write_bse_folded(project, state_nr, bse_folded_states):
    """
    Writes BSE folded states to a pickle file for later use.

    Parameters:
    - project: str, base name of the project used to name the output file.
    - state_nr: array-like, array of state numbers.
    - bse_folded_states: 2D numpy array, folded BSE states for each state in state_nr.

    Returns:
    - None
    """

    start_time = time.time()
    N_states = np.size(state_nr)
    N_i = state_nr[0]
    N_f = state_nr[-1]
    fname = f"{project}_bse_States_{int(N_i)}_{int(N_f)}.pkl"
    print(f"Writing BSE folded states to file: {fname}")
    
    with open(fname, "wb") as f:
        pickle.dump((state_nr, bse_folded_states), f)

    print(f"BSE folded states written to {fname} in {time.time() - start_time:.4f} seconds")

#%% Data structures

""" The e_k_dict contains parameters linked to one of the three relevant direction (100), (110) and (111). Scale is an
often used scaling for the distance, positive_dir sets the directions that will be oriented along a positive direction of 
a spatial axis (and therefore get a positive parallel distance). 'origin_bun' provides the coordinates of one line in a given bundle, 'kappa_0_bun'
gives the shift in parallel wavenumber when labeling a given segment in BZ1 in a given bundle. All this information is transfered
to each segment directory. 
"""

# Scaling factors for unit directions in different crystallographic orientations
l_110 = 1 / np.sqrt(2)   # Scaling factor for the (110) direction
l_111 = 1 / np.sqrt(3)   # Scaling factor for the (111) direction

# e_k_dict contains parameters for three crystallographic directions: (100), (110), and (111)
# Each entry in e_k_dict holds scaling, orientation, and origin information for a specific direction.
e_k_dict = [
    {
        'scale': 1,  # Scaling for the (100) direction
        'N_bun': 1,  # Number of bundles
        'positive_dir': np.array([  # Positive direction unit vectors for (100)
            [1, 0, 0],  # x-direction
            [0, 1, 0],  # y-direction
            [0, 0, 1]   # z-direction
        ]),
        'origin_bun': np.array([  # Origin points for the bundle
            [0, 0, 0],
            [1/2, 1/2, 1/2]
        ])
    },
    {
        'scale': l_110,  # Scaling for the (110) direction
        'N_bun': 1,
        'positive_dir': np.array([  # Positive direction unit vectors for (110)
            [l_110, l_110, 0],  # Along x and y axes
            [l_110, -l_110, 0],  # Along x and -y
            [0, l_110, l_110],   # Along y and z
            [0, l_110, -l_110],  # Along y and -z
            [l_110, 0, l_110],   # Along x and z
            [-l_110, 0, l_110]   # Along -x and z
        ]),
        'origin_bun': np.array([
            [0, 0, 0],
            [1/2, 1/2, 1/2]
        ])
    },
    {
        'scale': l_111,  # Scaling for the (111) direction
        'N_bun': 1,
        'positive_dir': np.array([  # Positive direction unit vectors for (111)
            [l_111, l_111, l_111],    # All positive directions
            [l_111, l_111, -l_111],   # z negative
            [l_111, -l_111, l_111],   # y negative
            [l_111, -l_111, -l_111]   # y and z negative
        ]),
        'origin_bun': np.array([
            [0, 0, 0],
            [1/2, 1/2, 1/2]
        ])
    }
]


