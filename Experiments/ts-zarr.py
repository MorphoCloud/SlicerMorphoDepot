import numpy

try:
  import tensorstore as ts
except ModuleNotFoundError:
  pip_install("tensorstore -vv")
  import tensorstore as ts


zarrURL = 'https://js2.jetstream-cloud.org:8001/swift/v1/sdp-morphodepot-data/UF-H-158477.zarr/0'

t = ts.open({
  'driver': 'zarr',
  'kvstore': zarrURL
})

print("Download")
tt = t.result()
a = tt.read().result()
print("Copy")
aa = numpy.copy(a)
print(aa.mean())
print("Show")
node = slicer.util.addVolumeFromArray(a)
slicer.util.setSliceViewerLayers(node, fit=True)
print("Done")
