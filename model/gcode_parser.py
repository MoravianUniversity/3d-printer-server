import numpy as np
import json
import operator
import functools


__all__ = ['gcode_to_json', 'gcode_to_obj']


def gcode_to_json(gcode,
                  include=range(7), extruder_separation=18,
                  ignore_support=False, ignore_infill=False,
                  out=None):
    """
    Converts a GCODE file to a JSON file which lists the lines for each extrude movements of the
    included cores (by default all cores).

    The gcode argument can be a file-like object (support iterating over lines), a list of GCODE
    lines, or a str with newlines in it.

    By default this function returns a str with the JSON contents, however by setting the out
    argument to a file object it will be directly written to the file which will likely be more
    efficient if writing to a file anyways.
    """
    if not include: return "{'layers':[]}"

    # The JSON data is like:
    # { layers: [[
    #     {
    #         height: h,
    #         z: z,
    #         lines: [
    #             [[x, y], ...],
    #             ...
    #         ]
    #     }, ...
    # ], ...] }

    extruder_lines = parse_gcode_file(gcode, include, ignore_support, ignore_infill)

    # Simplify
    extruder_lines = [simplify_lines(lines) for lines in extruder_lines]

    # Get the z levels and heights
    z_levels = get_z_levels(extruder_lines[0])
    for lines in extruder_lines[1:]:
        z_levels = np.unique([line[0, 2] for line in lines] + z_levels.tolist())
    heights = np.concatenate([[z_levels[0]], np.diff(z_levels)])

    # Get the lines in the layers
    layers_all = []
    for i, lines in enumerate(extruder_lines):
        layers = [{"z":(z-h/2).round(4), "height":h.round(4), "lines":[]}
                  for z, h in zip(z_levels, heights)]
        for line in lines:
            if i == 1:
                line[:, 0] += extruder_separation
            xy = line[:, :2].round(4).tolist()
            layer = get_layer_number(line, z_levels)
            layers[layer]["lines"].append(xy)
        layers_all.append(layers)

        # TODO: line widths based on E

    data = {'layers': layers_all}
    if out is None:
        return json.dumps(data, separators=(',', ':'))
    return json.dump(data, out, separators=(',', ':'))


def get_line_height(line, z_levels):
    """Gets the line height of a specific line by looking at the z levels."""
    z = line[0, 2]
    return z if z_levels[0] == z else \
        z - z_levels[get_layer_number(line[0, 2], z_levels)-1]


def get_layer_number(line, z_levels):
    """
    Get the layer number of a particular line from within the z levels.
    """
    return np.flatnonzero(z_levels == line[0, 2])[0]


def get_z_levels(lines):
    """Gets the unique z levels across all lines. Return value is in sorted order."""
    return np.unique([line[0, 2] for line in lines])


def simplify_lines(lines, area_tolerance=1e-2, sin_tolerance=1e-3):
    """
    Simplifies lines for a single extruder but combining (near-)colinear parts.

    The given lines as a list of n-by-3 or n-by-4 numpy array.

    Points are removed from lines if the triangle created by 3 consecutive points in a line has an
    area below the given tolerance (in mm^2, defaults to 1e-2 which is smaller than the area of a
    0.1mm nozzle) or if the sine of the angle of the third point in any triangle is below the other
    given tolerance (unitless number from 0 meaning perfectly collinear to 1 meaning perpendicular,
    defaults to 1e-3).

    Lines that only have 1 point are completely removed from the list. Lines with 2 points where
    the distance is less than the square root of the area tolerance are also completely removed
    from the list.
    """
    remove = []
    length_tolerance = np.sqrt(area_tolerance)

    for i, line in enumerate(lines):
        if line.shape[0] < 2:
            remove.append(i)
            continue
        is_cycle = (line[0, :2] == line[-1, :2]).all()

        # Simplify the lines
        while True:
            if line.shape[0] == 2 or is_cycle and line.shape[0] == 3:
                # check if too short and remove
                if np.linalg.norm(line[1] - line[0]) < length_tolerance:
                    remove.append(i)
                break

            # Compute the area and angle of every triangle (well, the sin of the angle)
            a, b, c = line[:-2, :3], line[1:-1, :3], line[2:, :3]
            area = np.linalg.norm(np.cross(a-c, b-c) / 2, axis=1)
            sin_theta = area / (np.linalg.norm(a-c, axis=1) * np.linalg.norm(b-c, axis=1))

            # Compare to the tolerances
            keep = (area > area_tolerance) & (sin_theta > sin_tolerance)
            if np.all(keep): break

            # Only keep some of the lines
            keep = np.pad(keep, 1, constant_values=True)
            line = line[keep]
        lines[i] = line

    for i in reversed(remove):
        del lines[i]

    return lines


def parse_gcode_file(gcode, include=range(7), ignore_support=False, ignore_infill=False):
    """
    Parses a GCODE file line by line looking for G0/G1 commands along with T#, G28, G90, G91, G92,
    M82, and M83 commands which influence G0/G1.

    Returns the points visited by all G0/G1 commands that resulted in a positive extrusion from an
    included core as a list-of-list-of-numpy-arrays with the outer list has 1 element for each
    included core, the inner list is each line of points, and the numpy arrays are n-by-4 where n
    is the number of consecutive points visited during an extrude and the 4 values are x, y, z, and e.

    The optional arguments for ignore_support and ignore_infill can be used to ignore those types
    of lines if set to true and the GCODE uses the Cura-added ;TYPE comments before the different
    line types.
    """
    if len(include) == 0:
        return []
    if isinstance(gcode, str):
         gcode = gcode.splitlines()

    COORD = "XYZE"
    SUPPORT_TYPES = ("SKIRT", "SUPPORT", "SUPPORT-INTERFACE", "PRIME-TOWER")
    INFILL_TYPES = ("FILL",)

    lines = [[[]] for _ in range(len(include))]
    cur_lines = lines[0]
    max_used_core = 0

    current_pt = [0.0, 0.0, 0.0, 0.0]  # x, y, z, e
    e_change = [0.0] * len(include)
    printcore = 0
    skipping_type = False

    relative_pos = [0.0, 0.0, 0.0, 0.0]
    op = lambda a, b: b  # default is absolute positioning (just uses b)
    extruder_op = op  # extruder can be independent of other positions

    for gcode_line in gcode:
        # Check the type (which is actually a comment so has to be done first)
        if gcode_line.startswith(";TYPE:"):
            cur_type = gcode_line[6:].strip()
            skipping_type = (ignore_support and cur_type in SUPPORT_TYPES or
                             ignore_infill and cur_type in INFILL_TYPES)
            continue

        # Remove comments and skip empty lines
        semicolon = gcode_line.find(';')
        if semicolon != -1:
            gcode_line = gcode_line[:semicolon]
        gcode_line = gcode_line.strip()
        if not gcode_line:
            continue
        parameters = gcode_line.split()
        command = parameters[0]
        parameters = parameters[1:]

        # Checking for when the active core is switched
        if command[0] == "T" and command[1:] in tuple('0123456'):
            printcore = int(command[1])
            if printcore in include:
                cur_lines = lines[include.index(printcore)]
                if printcore > max_used_core:
                    max_used_core = printcore

        # Set to absolute positioning
        elif command == "G90":
            op = extruder_op = lambda a, b: b
        # Set to relative positioning
        elif command == "G91":
            op = extruder_op = operator.add
        # Set just extruder to absolute positioning
        elif command == "M82":
            extruder_op = lambda a, b: b
        # Set just extruder to relative positioning
        elif command == "M83":
            extruder_op = operator.add

        # Sets the current position as the given value
        # We have to then translate this into a physical-world coordinate using relative_pos
        elif command == "G92":
            for p in parameters:
                idx = COORD.find(p[0])
                if idx != -1:
                    relative_pos[idx] += current_pt[idx]
                    current_pt[idx] = float(p[1:])

        # G0 or G1 is for movement, G0 typically used for non-extrusion, G1 for extrusion
        elif command in ("G0", "G1"):
            last_e = current_pt[3]

            # Going through command parameters to get info out
            # This uses op() which is either add (for relative positioning) or take the second argument (for absolute positioning)
            for p in parameters:
                idx = COORD.find(p[0])
                if idx != -1:
                    value = float(p[1:])
                    if idx == 3:  # E
                        current_pt[3] = extruder_op(current_pt[3], value)
                    else:  # X, Y, or Z
                        current_pt[idx] = op(current_pt[idx], value)

            if printcore in include:
                # Check if this extrusion is actually pushing material out of the nozzle
                # Need to pay attention to retractions, and how far filament is pulled out of the nozzle at times
                # Thus, if e_change becomes negative, we want to keep it negative until there are enough positive changes to bring it back
                pci = include.index(printcore)
                e_change[pci] = (e_change[pci] if e_change[pci] <= 0 else 0) + current_pt[3] - last_e

                # Not extruding on this move, so now start a new line
                if e_change[pci] <= 0.0:
                    if len(cur_lines[-1]) <= 1:
                        cur_lines[-1].clear()
                    else:
                        cur_lines.append([])

                pt = [c+r for c, r in zip(current_pt, relative_pos)]

                if not skipping_type:
                    cur_lines[-1].append(pt)


    # Remove all single-point 'lines' and convert to numpy arrays
    for i in range(len(lines)):
        lines[i] = [np.array(line) for line in lines[i] if len(line) > 1]

    # Remove all lines on unused cores
    remove = [include.index(printcore) for printcore in include if printcore > max_used_core]
    remove.sort(reverse=True)
    for printcore in remove:
        del lines[printcore]

    return lines



# ----------------------------
# For OBJ files


def get_vertices(line, line_height, line_width):
    """
    Computes all of the vertices necessary to draw rectangular boxes around the line.
    This will include four times as many vertices as the number of points in the line.
    The two vertices that lie on the current plane are in the first half of the return value and
    the two vertices that lie on the plane above are in the second half of the data. Within a half,
    the vertices alternate between left and right around a single point on the line.
    """
    # TODO: dynamically determine line width
    # it depends on the extrusion amount over a given distance (but will still need some info like material diameter)
    # dist = np.linalg.norm(line[1:, :2] - line[:-1, :2], axis=1)
    # e = 2.85*2.85*np.pi * (line[1:, 3] - line[:-1, 3]) / dist  # mm - volume of plastic put down per mm
    # e_spread = e / (line_height*2)  # amount of distance plastic spreads out in either left or right direction
    # seems to work out sometimes, but other times it is WAY off

    num_pts = len(line)
    line_width /= 2  # only goes halfway to the left and right

    # allocate memory
    vertices_all = np.empty((num_pts*4, 3))
    vertices = vertices_all[num_pts*2:]

    if num_pts <= 1: return vertices_all

    # generate the bulk of the vertices
    a, b, c = line[:-2, :3], line[1:-1, :3], line[2:, :3]
    prev_diff = b - a
    next_diff = b - c
    normals = np.stack([-prev_diff[:, 1], prev_diff[:, 0], prev_diff[:, 2]]).T
    need_next = (prev_diff[:, :2] == next_diff[:, :2]).all(1)
    next_normal = np.stack([next_diff[:, 1], -next_diff[:, 0], next_diff[:, 2]]).T
    normals[need_next] += next_normal[need_next]
    scale = np.linalg.norm(normals, axis=1)
    scale[scale==0] = 1
    normals *= line_width/scale[:, None]

    np.subtract(b, normals, vertices[2:-2:2])  # vertices[2:-2:2] = b - normals
    np.add(     b, normals, vertices[3:-2:2])  # vertices[3:-2:2] = b + normals

    # first vertices
    vector = line[1, :3] - line[0, :3]
    scale = np.linalg.norm(vector) or 1
    normal = np.array((-vector[1], vector[0], vector[2])) * (line_width/scale)
    vertices[0] = line[0, :3] - normal
    vertices[1] = line[0, :3] + normal

    # last vertices
    vector = line[-1, :3] - line[-2, :3]
    scale = np.linalg.norm(vector) or 1
    normal = np.array((-vector[1], vector[0], vector[2])) * (line_width/scale)
    vertices[-2] = line[-1, :3] - normal
    vertices[-1] = line[-1, :3] + normal

    # add the upper part
    np.subtract(vertices, [0, 0, line_height], vertices_all[:num_pts*2]) # vertices_all[:num_pts*2] = vertices - np.array([0, 0, line_height])

    return vertices_all


@functools.lru_cache(maxsize=1024)
def create_faces(n):
    """
    Creates all of the necessary faces for a line of the given size. The indices start at 0.
    """
    n *= 2
    indices = np.empty((4*n-4, 3), int)
    is_ = np.arange(0, n-2, 2)
    is_1 = is_ + 1
    is_2 = is_ + 2
    is_3 = is_ + 3
    is_n = is_ + n
    is_n_1 = is_n + 1
    is_n_2 = is_n + 2
    is_n_3 = is_n + 3

    # Bottom
    indices[:-4:8, 0] = is_
    indices[:-4:8, 1] = is_1
    indices[:-4:8, 2] = is_3
    indices[1:-4:8, 0] = is_
    indices[1:-4:8, 1] = is_3
    indices[1:-4:8, 2] = is_2
    # Top
    indices[2:-4:8, 0] = is_n
    indices[2:-4:8, 1] = is_n_3
    indices[2:-4:8, 2] = is_n_1
    indices[3:-4:8, 0] = is_n
    indices[3:-4:8, 1] = is_n_2
    indices[3:-4:8, 2] = is_n_3
    # Right
    indices[4:-4:8, 0] = is_
    indices[4:-4:8, 1] = is_2
    indices[4:-4:8, 2] = is_n
    indices[5:-4:8, 0] = is_2
    indices[5:-4:8, 1] = is_n_2
    indices[5:-4:8, 2] = is_n
    # Left
    indices[6:-4:8, 0] = is_1
    indices[6:-4:8, 1] = is_n_1
    indices[6:-4:8, 2] = is_3
    indices[7:-4:8, 0] = is_3
    indices[7:-4:8, 1] = is_n_1
    indices[7:-4:8, 2] = is_n_3

    # for i in range(0, n-2, 2):
    #     # Bottom
    #     indices[4*i]   = [i,  i+1,  i+3]
    #     indices[4*i+1] = [i,  i+3,  i+2]
    #     # Top
    #     indices[4*i+2] = [i+n,i+3+n,i+1+n]
    #     indices[4*i+3] = [i+n,i+2+n,i+3+n]
    #     # Right
    #     indices[4*i+4] = [i,  i+2,  i  +n]
    #     indices[4*i+5] = [i+2,i+2+n,i  +n]
    #     # Left
    #     indices[4*i+6] = [i+1,i+1+n,i+3  ]
    #     indices[4*i+7] = [i+3,i+1+n,i+3+n]
    
    indices[-4] = [0,n+1,1] # Front
    indices[-3] = [0,n,n+1]
    indices[-2] = [n-2,n-1,(n*2)-1] # Back
    indices[-1] = [n-2,(n*2)-1,(n*2)-2]
    return indices


def gcode_to_obj(gcode,
                 include=range(7), extruder_separation=18,
                 ignore_support=False, ignore_infill=False,
                 out=None):
    """
    Converts a GCODE file to an OBJ file. The gcode argument can be a file-like object (support
    iterating over lines), a list of GCODE lines, or a str with newlines in it.
    """
    # TODO: use extruder_separation somewhere
    extruder_lines = parse_gcode_file(gcode, include, ignore_support, ignore_infill)

    vertices = []
    facets = []
    offset = 0
    #counts = []

    for lines in extruder_lines:
        lines = simplify_lines(lines)

        z_levels = get_z_levels(lines)
        for line in lines:
            vertices.append(get_vertices(line, get_line_height(line, z_levels), 0.8*0.4))

        for line in lines:
            facets.append(create_faces(len(line)) + offset)
            offset += len(line)*4
    #counts.append(offset - (counts[-1] if counts else 0))

    if len(vertices) == 0:
        return ""
    
    vertices = np.concatenate(vertices)
    facets = np.concatenate(facets)

    import trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=facets)
    obj = trimesh.exchange.export.export_obj(mesh, digits=4)
    if out is None:
        return obj
    out.write(obj)
