import numpy as np
import trimesh


__all__ = ['gcode_to_obj']


def gcode_to_obj(gcode_lines, include=(0,), extruder_separation=18):
    # The printcores in an Ultimaker 3 are about 18 millimeters apart. I'll need to measure this later to be sure.
    extruder_layers = parse_gcode_file(gcode_lines, extruder_separation)

    vertices = []
    indices = []
    counts = []

    for i in include:
        for layer in extruder_layers[i]:
            for line in layer:
                if len(line) > 1:
                    normal_points = get_corner_normals(line, 0.2)
                    new_vertices, new_indices = build_mesh_from_points(normal_points, 0.2)
                    new_indices = list(np.array(new_indices) + len(vertices))
                    vertices += new_vertices
                    indices += new_indices
        counts.append(len(vertices) - (counts[-1] if counts else 0))

    # TODO: make separate OBJ objects if len(include) > 1
    #object_color = [0.5, 0.5, 0.5]
    #support_color = [0.87, 0.84, 0.67]
    #colors = [object_color] * counts[0] + [support_color] * counts[1]
    test = trimesh.Trimesh(vertices=vertices, faces=indices) # , vertex_colors=colors
    return trimesh.exchange.export.export_obj(test)


def build_mesh_from_points(points, line_height):
    point_count = len(points)
    second_layer = np.array(points) + np.array([0,0,line_height])
    indices = []

    #Front Face
    indices += [[0,point_count+1,1],[0,point_count,point_count+1]]

    #Back Face
    indices += [[point_count-2,point_count-1,(point_count*2)-1],[point_count-2,(point_count*2)-1,(point_count*2)-2]]

    i=0
    while i < point_count-2:
        #Bottom layer
        indices += [[i,i+1,i+3],[i,i+3,i+2]]
        #Top Layer
        indices += [[point_count+i,point_count+i+3,point_count+i+1],[point_count+i,point_count+i+2,point_count+i+3]]
        #Right Layer
        indices += [[i,i+2,i+point_count],[i+2,i+2+point_count,i+point_count]]
        #Left Layer
        indices += [[i+1,i+1+point_count,i+3],[i+3,i+1+point_count,i+3+point_count]]
        i+=2

    points += list(second_layer)
    return points, indices

def rotate_vector(vector, angle):
    return [vector[0]*np.cos(angle) - vector[1]*np.sin(angle), vector[0]*np.sin(angle) + vector[1]*np.cos(angle)]

def calc_normal(vector, length):
    normal = []
#     if vector[0] == 0 or vector[1] == 0:
#         normal = [vector[1], vector[0]]
    if vector[0] == 0:
        #If one of the values is 0, flip x & y to get normal
        normal = [length,0]
    elif vector[1] == 0:
        #If one of the values is 0, flip x & y to get normal
        normal = [0,-length]
    else:
        normal = [1/vector[0], -1/vector[1]]

        #Scaling to be length
        mag = np.sqrt(normal[0]**2 + normal[1]**2)
        normal = length*(np.array(normal)/mag)

    return normal

def scale_vector(vector, length):
    mag = np.sqrt(vector[0]**2 + vector[1]**2)
    vector = length*(np.array(vector)/mag)
    return vector


def add_vector_bi(vector, point):
    '''
    Takes a vector and point, returns point + vector and point - vector
    '''
    new_point_pos = [point[0] + vector[0], point[1] + vector[1], point[2]]
    new_point_neg = [point[0] - vector[0], point[1] - vector[1], point[2]]
    return (new_point_pos, new_point_neg)


def get_corner_normals(line, line_width):

    result = []

    # TODO: make width be based on variable, on extrusion amount
    width = line_width

    if len(line) > 1:

        #Getting vector normal to very first line, to get our starting points
        # first_normal = calc_normal([line[1][0] - line[0][0], line[1][1] - line[0][1]], width)
        first_normal = scale_vector(rotate_vector([line[1][0] - line[0][0], line[1][1] - line[0][1]], np.pi/2), width)
        start_points = add_vector_bi(first_normal, line[0])
        result.append(start_points[0])
        result.append(start_points[1])

        for i in range(1, len(line) - 1):
            last_point = line[i - 1]
            current_point = line[i]
            next_point = line[i + 1]

            last_dif = [current_point[0] - last_point[0], current_point[1] - last_point[1]]
            next_dif = [current_point[0] - next_point[0], current_point[1] - next_point[1]]

#             last_normal = calc_normal(last_dif, width)
            last_normal = rotate_vector(last_dif, np.pi/2)

#             next_normal = calc_normal(next_dif, width)
            next_normal = rotate_vector(next_dif, -np.pi/2)


            """
            Fixing a problem where the calculated normal flips across the line

            When you have two points, and the vector between them has [-x,y] or [x,-y],
            the calculated (as done in this code) normal of the vector will be to the vector's right,
            if 'forward' is from the second point to the first
            If the vector has [-x,-y] or [x,y] it will be to the vector's left
            The problem is that, for any given iteration, one normal might be to the left and the other
            might be to the right of their respective vectors, or they might both be left or whatever
            When they both are left or both are right, the final calculated points end up effectively rotated 90 degrees
            To fix this, we make sure that last_normal is always to the left, and next_normal is always
            to the left; it seems that what matters is that they both be on different sides of their
            respective vectors
            (which, if you looked at the vectors plotted from current_point, would look like they're on the same side,
            since the vectors are calculated starting from current_point, going out/away from it)
            """
#             if (last_dif[0] >= 0 and last_dif[1] <= 0) or (last_dif[0] <= 0 and last_dif[1] >= 0):
#                 last_normal = [-1 * last_normal[0], -1 * last_normal[1]]

#             if (next_dif[0] >= 0 and next_dif[1] >= 0) or (next_dif[0] <= 0 and next_dif[1] <= 0):
#                 next_normal = [-1 * next_normal[0], -1 * next_normal[1]]

            #https://math.stackexchange.com/questions/274712/calculate-on-which-side-of-a-straight-line-is-a-given-point-located
            #https://stackoverflow.com/questions/13221873/determining-if-one-2d-vector-is-to-the-right-or-left-of-another#13221874
#             if dot_product(last_dif, last_normal) < 0:
#                 last_normal = [-1 * last_normal[0], -1 * last_normal[1]]

#             if dot_product(next_dif, next_normal) < 0:
#                 next_normal = [-1 * next_normal[0], -1 * next_normal[1]]

            normal = []
            if last_normal[0] == next_normal[0]*-1 and last_normal[1] == next_normal[1]*-1:
                normal = last_normal
            else:
                normal = [(last_normal[0] + next_normal[0]), (last_normal[1] + next_normal[1])]

            #Scaling result back to width
            magnitude = np.sqrt(normal[0]**2 + normal[1]**2)
            normal = [(normal[0] / magnitude) * width, (normal[1] / magnitude) * width]

            corner_points = add_vector_bi(normal, current_point)

            result.append(corner_points[0])
            result.append(corner_points[1])

        #Getting vector normal to very last line, to get our ending points
        # last_normal = calc_normal([line[-1][0] - line[-2][0], line[-1][1] - line[-2][1]], width)
        last_normal = scale_vector(rotate_vector([line[-1][0] - line[-2][0], line[-1][1] - line[-2][1]], np.pi/2), width)
        end_points = add_vector_bi(last_normal, line[-1])
        result.append(end_points[0])
        result.append(end_points[1])

    return result


def parse_gcode_file(lines, hotend_distance=0):

    one_layers = []
    two_layers = []

    one_lines = []
    two_lines = []

    one_new_line = []
    two_new_line = []

    current_x = 0.0
    current_y = 0.0
    current_z = 0.0
    last_extruded_z = 0.0
    last_e = 0.0
    e_change = 0.0

    core_switch_save = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    printing = False

    printcore = 0

    count = 0
    for line in lines:

        #Need to check if this line has or is a comment, and shave off the comment or skip it if it is/does, respectively
        line = line.split(";")[0]
        if line == "":
            continue


        #Checking for when the active core is switched
        if line[:2] == "T0" or line[:2] == "T1":
            new_core = int(line[1])
            #In case T0 or T1 commands get called for some reason while we're still on the same core
            #I don't think that'll ever happen but I want the code to work if it does
            if new_core != printcore:
                printcore = new_core
                current_values = [current_x, current_y, current_z, last_extruded_z, last_e, e_change]
                current_x = core_switch_save[0]
                current_y = core_switch_save[1]
                current_z = core_switch_save[2]
                last_extruded_z = core_switch_save[3]
                last_e = core_switch_save[4]
                e_change = core_switch_save[5]
                core_switch_save = current_values


        #Only start recording once we see this command. M204 prolly would work too.
        if line[:4] == "M205":
            printing = True

        if printing:
            #G0 or G1 = movement, G0 typically used for non-extrusion, G1 for extrusion
            if line[:2] == "G0" or line[:2] == "G1":

                parameters = line.split(" ")

                new_x = current_x
                new_y = current_y
                new_z = current_z
                new_e = last_e

                #Going through command parameters to get info out. Can skip first thing in list since it'll just be G0 or G1
                for p in parameters[1:]:
                    if p == "":
                        continue

                    if p[0] == "X":
                        new_x = float(p[1:])
                        # Position of the printhead in gcode doesn't care about which hotend we're using, so our slicer needs to shift over a bit so the second hotend is aligned correctly. Here, we undo this shifting so we record the actual coordinates that the nozzle moved over.
                        if printcore == 1:
                            new_x += hotend_distance
                    elif p[0] == "Y":
                        new_y = float(p[1:])
                    elif p[0] == "Z":
                        new_z = float(p[1:])
                    elif p[0] == "E":
                        new_e = float(p[1:])

                did_extrude = False
                # If E is specified, we're extruding on this move
                # This is probably not necessary since the code as it is would give 0 e_change for lines without 'E' in them, but I'll leave this in just to be safe
                if "E" in line and ("X" in line or "Y" in line or "Z" in line):

                    # Check if this extrusion is actually pushing material out of the nozzle
                    # Need to pay attention to retractions, and how far filament is pulled out of the nozzle at times
                    # Thus, if e_change becomes negative, we want to keep it negative until there are enough positive changes to bring it back
                    extrusion_dif = new_e - last_e
                    if e_change <= 0:
                        e_change = e_change + extrusion_dif
                    else:
                        e_change = extrusion_dif

#                     print(e_change)

                    # Only record these movements if we're actually extruding
                    if e_change > 0.0:
                        did_extrude = True

                        #Check if we're starting a new layer, and start adding to a new layer if so
                        if new_z != last_extruded_z:
                            if printcore == 0:
                                one_layers.append(one_lines)
                                one_lines = []
                                one_new_line = []
                            else:
                                two_layers.append(two_lines)
                                two_lines = []
                                two_new_line = []
                        if printcore == 0:
                            one_new_line.append([new_x, new_y, new_z])
                        else:
                            two_new_line.append([new_x, new_y, new_z])
                        last_extruded_z = new_z

                #Not extruding on this move, so now start a new line/maybe point(s) if there are multiple non-extrusion moves
                if not did_extrude:
                    if printcore == 0:
                        if len(one_new_line) > 1:
                            one_lines.append(one_new_line)
                        one_new_line = []
                        one_new_line.append([new_x, new_y, new_z])
                    else:
                        if len(two_new_line) > 1:
                            two_lines.append(two_new_line)
                        two_new_line = []
                        two_new_line.append([new_x, new_y, new_z])

                current_x = new_x
                current_y = new_y
                current_z = new_z


    #Removing first layer, since our first command will go to the starting Z coordinate and thus add an empty list to layers
    one_layers = one_layers[1:]
    two_layers = two_layers[1:]

    return one_layers, two_layers
