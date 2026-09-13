import os
import sys
import ctypes
import ctypes.wintypes
import subprocess

cred_name = 'GitHub - https://api.github.com/OrcusExtreme'
advapi32 = ctypes.windll.advapi32

class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ('Flags', ctypes.wintypes.DWORD),
        ('Type', ctypes.wintypes.DWORD),
        ('TargetName', ctypes.wintypes.LPWSTR),
        ('Comment', ctypes.wintypes.LPWSTR),
        ('LastWritten', ctypes.wintypes.FILETIME),
        ('CredentialBlobSize', ctypes.wintypes.DWORD),
        ('CredentialBlob', ctypes.c_char_p),
        ('Persist', ctypes.wintypes.DWORD),
        ('AttributeCount', ctypes.wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', ctypes.wintypes.LPWSTR),
        ('UserName', ctypes.wintypes.LPWSTR)
    ]

PCREDENTIAL = ctypes.POINTER(CREDENTIAL)
advapi32.CredReadW.argtypes = [ctypes.wintypes.LPWSTR, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.POINTER(PCREDENTIAL)]

pcred = PCREDENTIAL()
ok = advapi32.CredReadW(cred_name, 1, 0, ctypes.byref(pcred))
if not ok:
    print("Could not read credential")
    sys.exit(1)

blob = ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
token = blob.decode('utf-8', errors='ignore').strip()

subprocess.run(['git', 'add', '-A'], check=True)
subprocess.run(['git', 'commit', '-m', 'Refactor: Eliminate redundant duplicate files and harden edge-case logic'], check=True)

auth_url = f"https://OrcusExtreme:{token}@github.com/OrcusExtreme/ORCUS-Downloader.git"
push_res = subprocess.run(['git', 'push', auth_url, 'main'], capture_output=True, text=True)
print("Push output:", push_res.stdout)
print("Push error:", push_res.stderr)
if push_res.returncode == 0:
    print("Pushed successfully to GitHub!")
