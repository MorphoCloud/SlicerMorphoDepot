import subprocess
import os

startupInfo = None
if os.name == "nt":
    # Hide console window (only needed on Windows)
    startupInfo = subprocess.STARTUPINFO()
    startupInfo.dwFlags = 1
    startupInfo.wShowWindow = 0

ghPath = "/Users/pieper/slicer/latest/SlicerMorphoDepot/MorphoDepot/Resources/pixi/.pixi/envs/default/bin/gh"

cmd = [ghPath,
       "auth", "login",
       "--hostname", "github.com",
       "--git-protocol", "https",
       "--web"]

print(" ".join(cmd))

proc = subprocess.Popen(cmd,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True,
                        startupinfo=startupInfo)

while line = proc.stdout.readline() != '':
    

