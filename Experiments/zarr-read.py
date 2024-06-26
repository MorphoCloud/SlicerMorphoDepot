
notes = """

object store in dashboard at https://js2.jetstream-cloud.org/project/

https://js2.jetstream-cloud.org/project/containers/container/sdp-morphodepot-data

https://js2.jetstream-cloud.org/project/containers/container/sdp-morphodepot-data/UF-H-158477.zarr

https://js2.jetstream-cloud.org:8001/swift/v1/sdp-morphodepot-data/UF-H-158477.zarr/.zattrs


"""


import itk

zarrURL = "https://js2.jetstream-cloud.org:8001/swift/v1/sdp-morphodepot-data/UF-H-158477.zarr"
imageio = itk.OMEZarrNGFFImageIO.New()
image = itk.imread(zarrURL, imageio=imageio)

a = itk.GetArrayViewFromImage(image)
print(a.shape)
print(a.max())
node = slicer.util.addVolumeFromArray(a)

//itk.imwrite(image, sys.argv[2], imageio=imageio, compression=False)
