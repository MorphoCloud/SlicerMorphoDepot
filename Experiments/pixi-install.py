
# mac / linux
curl -fsSL https://pixi.sh/install.sh | PIXI_HOME=/tmp/pixi PIXI_NO_PATH_UPDATE=1 bash

mkdir -p /tmp/pixi-test-env
cd /tmp/pixi-test-env

/tmp/pixi/bin/pixi init .
/tmp/pixi/bin/pixi add git
/tmp/pixi/bin/pixi add gh


# windows

scriptPath = slicer.app.temporaryPath + "/pixi-install.ps1"
slicer.util.downloadFile("https://pixi.sh/install.ps1", scriptPath)
command = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", scriptPath , "-PixiHome", slicer.app.temporaryPath, "-NoPathUpdate"]

