import os
import sys

ghDownloadURLs = {
    "linux2" : "https://github.com/cli/cli/releases/download/v2.66.1/gh_2.66.1_linux_amd64.tar.gz",
    "darwin" : "https://github.com/cli/cli/releases/download/v2.66.1/gh_2.66.1_macOS_amd64.zip",
    "win32" : "https://github.com/cli/cli/releases/download/v2.66.1/gh_2.66.1_windows_amd64.zip"
}

url = ghDownloadURLs[sys.platform]
fileName = url.split("/")[-1]

modulePath = "/".join(slicer.modules.morphodepot.path.split("/")[:-1])
resourcesPath = modulePath + "/Resources"
downloadPath = resourcesPath + "/" + fileName
if fileName.endswith(".tar.gz"):
    archiveDirName = fileName[:-len('.tar.gz')]
elif fileName.endswith(".zip"):
    archiveDirName = fileName[:-len('.zip')]
else:
    print("bad archive extension")

slicer.util.downloadFile(url, downloadPath)

if sys.platform == "linux2":
    fileName = url.split("/")[-1]
    bashCommand = ["/bin/bash", "-c", f"(cd {resourcesPath}; tar xfz {fileName})"]
    bashProcess = slicer.util.launchConsoleProcess(bashCommand)
    if bashProcess.wait() != 0:
        print("Could not open archive")
        print(bashProcess.communicate())
    ghPath = f"{resourcesPath}/{archiveDirName}/bin/gh"
elif sys.platform == "darwin":
    unzipPath = resourcesPath + "/" + archiveDirName
    archive = slicer.vtkArchive()
    archive.UnZip(downloadPath, resourcesPath)
    ghPath = f"{unzipPath}/bin/gh"
elif sys.platform == "darwin" or sys.platform == "win32":
    unzipPath = resourcesPath + "/" + archiveDirName
    os.makedirs(unzipPath, exist_ok=True)
    archive = slicer.vtkArchive()
    archive.UnZip(downloadPath, unzipPath)
    ghPath = f"{unzipPath}/bin/gh.exe"
else:
    print(f"unknown platform {sys.platform}")

print(slicer.util.launchConsoleProcess(ghPath).communicate())

os.remove(downloadPath)
