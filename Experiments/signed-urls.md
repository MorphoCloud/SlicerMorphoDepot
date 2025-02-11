Based on info from here: https://cloud.google.com/storage/docs/access-control/signing-urls-with-helpers#command-line_1

Create GCS bucket, i.e. sdp-signed-url-tests

Create service account, i.e. sdp-signedurl-test-sa@idc-external-031.iam.gserviceaccount.com

Give service acount permissions Storage Object Creator, Storage Object User, Storage Object Viewer

Create a key for the service account:
```
gcloud iam service-accounts keys create sdp-key --iam-account=sdp-signedurl-test-sa@idc-external-031.iam.gserviceaccount.com
```

Create signed url that enables PUT:
```
gcloud storage sign-url gs://sdp-signed-url-tests/upload1 --region=us-central1 --private-key-file=sdp-key --duration=1d --http-verb=PUT --headers=content-type=application/octet-stream
```

Use the generated signed url to upload:
```
curl -X PUT -H 'Content-Type: application/octet-stream' --upload-file /tmp/test.zarr/0/0/0/0 "https://storage.googleapis.com/sdp-signed-url-tests/upload1?x-goog-signature=5a6ed16f58c647b9f7a6e072e9b9b58131302f1060c2b5443a5a9d1fff9189d11c55af962b64796859ab10536b78710d29b5224954c137a5826305bc951a1c82fcd5df1a53ae1dbdf215be08f78817bb429b6bca6ffd05278909bf2b02a616024161005a090294de69a679807e1eeb9021c991679ae74845cc18838c79ce28dbcfd4695e956f8198a79a13e9b3f96e57510fd16dd7c2c80a28319035ca869e68d3cfa965e7ab8f66db919ca287a044edf33b9af816ad91f841771451a31c1bf5ed87ccb7823e61c2699dd010e79feab6e65a2334ad44e6df4e65ae4fc3a6a42128aa73f828abec0ae13e63692f9310d7f9c6d2ea244671ab4b94f45c0e35d1b9&x-goog-algorithm=GOOG4-RSA-SHA256&x-goog-credential=sdp-signedurl-test-sa%40idc-external-031.iam.gserviceaccount.com%2F20250211%2Fus-central1%2Fstorage%2Fgoog4_request&x-goog-date=20250211T202809Z&x-goog-expires=86400&x-goog-signedheaders=content-type%3Bhost"
```

Issues: 
- need one URL per zarr chunk
- involves GCS instead of pure gh

