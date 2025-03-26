import subprocess
import os

startupInfo = None
if os.name == "nt":
    # Hide console window (only needed on Windows)
    startupInfo = subprocess.STARTUPINFO()
    startupInfo.dwFlags = 1
    startupInfo.wShowWindow = 0

ghPath = "/Users/pieper/slicer/latest/SlicerMorphoDepot/MorphoDepot/Resources/pixi/.pixi/envs/default/bin/gh"
ghPath = "/home/exouser/SlicerMorphoDepot/MorphoDepot/Resources/pixi/.pixi/envs/default/bin/gh"

oldHOME = os.environ["HOME"]
os.environ["HOME"] = "/home/exouser/SlicerMorphoDepot/MorphoDepot/Resources/pixi"

cmd = [ghPath,
       "auth", "login",
       "--hostname", "github.com",
       "--git-protocol", "https"
]

print(" ".join(cmd))

proc = subprocess.Popen(cmd,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        universal_newlines=True,
                        startupinfo=startupInfo)

proc.stdout.readline() # blank
codeLine = proc.stdout.readline()
print(codeLine)
code = codeLine.split()[-1]
urlLine = proc.stdout.readline()
print(urlLine)
url = urlLine.split()[-1]

print(code)


webWidget = slicer.qSlicerWebWidget()
webWidget.url = url
webWidget.size = qt.QSize(700, 700)
slicerPos = slicer.util.mainWindow().pos
webWidget.pos = qt.QPoint(30 + slicerPos.x(), 50+slicerPos.y())
webWidget.show()
slicer.app.processEvents()


label = qt.QLabel(f"\n\n-->\t\tLog into GitHub and then type in this code when prompted: {code}\t\t<--\n\n")
label.pos = qt.QPoint(750+slicerPos.x(), 250+slicerPos.y())
label.show()

slicer.app.processEvents()

os.environ["HOME"] = oldHOME
