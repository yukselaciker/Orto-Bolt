import sys
import pyvista as pv

print("Testing pick event...", flush=True)

sphere = pv.Sphere()
plotter = pv.Plotter(off_screen=True)
plotter.add_mesh(sphere)

picks = []
def _on_pick(point):
    print("Picked:", point, flush=True)
    picks.append(point)

plotter.enable_point_picking(callback=_on_pick, left_clicking=True, show_message=False)

print("Pick event enabled", flush=True)
