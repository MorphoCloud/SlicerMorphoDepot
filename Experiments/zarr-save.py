import numpy
import os

try:
    import zarr
except:
    pip_install("zarr")
    import zarr

try:
    import ome_zarr
except:
    pip_install("ome-zarr")

import ome_zarr
import ome_zarr.io
import ome_zarr.writer

path = "/tmp/test.zarr"
if not os.path.exists(path):
    os.mkdir(path)

data = slicer.util.array("UF-H-158477")

store = ome_zarr.io.parse_url(path, mode="w").store
root = zarr.group(store=store)
options = dict(chunks=[data.shape[0]/10, data.shape[1], data.shape[2]])
ome_zarr.writer.write_image(image=data, group=root, axes="xyx", storage_options=options)
