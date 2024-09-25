import os

repoPIemail = "pieper@isomics.com"
keyFile = os.path.expanduser("~/.ssh/id_ed25519-MD_E15")

if not os.path.exists(keyFile):
    print("need to set up github keys")
    result = os.system(f"ssh-keygen -t ed25519 -C {repoPIemail} -N '' -f {keyFile}")
    if result != 0:
        print("Couldn't create key")
