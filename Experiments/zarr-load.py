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
import ome_zarr.reader

#url = "https://uk1s3.embassy.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr"
zarrURL = "https://js2.jetstream-cloud.org:8001/swift/v1/sdp-morphodepot-data/UF-H-158477.zarr"

# read the image data
store = ome_zarr.io.parse_url(zarrURL, mode="r").store

reader = ome_zarr.reader.Reader(ome_zarr.io.parse_url(zarrURL))
# nodes may include images, labels etc
nodes = list(reader())
# first node will be the image pixel data
imageDask = nodes[0].data[0]
a = numpy.array(imageDask)
addVolumeFromArray(a)
