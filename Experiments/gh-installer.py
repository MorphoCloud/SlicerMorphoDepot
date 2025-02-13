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
archiveName = fileName[:-len('.tar.gz')]

slicer.util.downloadFile(url, downloadPath)


if sys.platform == "linux2":
    fileName = url.split("/")[-1]
    bashCommand = ["/bin/bash", "-c", f"(cd {resourcesPath}; tar xfz {fileName})"]
    bashProcess = slicer.util.launchConsoleProcess(bashCommand)
    if bashProcess.wait() != 0:
        print("Could not open archive")
        print(bashProcess.communicate())
    ghPath = f"{resourcesPath}/{archiveName}/bin/gh"

    print(slicer.util.launchConsoleProcess(ghPath).communicate())
    

