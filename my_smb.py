#ref: 
import platform
import os
import io
from pathlib import Path

from smb.SMBConnection import SMBConnection
from smb.smb_structs import OperationFailure

class Smb():
    def __init__(self, username, password, remote_name, ip):
        self.conn = SMBConnection(username, password, platform.node(), remote_name)
        self.ip = ip

    def __enter__(self):
        self.conn.connect(self.ip)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.conn.close()

    def echo(self, data):
        return self.conn.echo(data)

    def send_file(self, local_file, svc_name, remote_dir):
        if not os.path.isfile(local_file):
            print("invalid path: {}".format(local_file))
            return False

        try:
            if not self.conn.getAttributes(svc_name, remote_dir).isDirectory:
                print("invalid remote path: {} - {}".format(svc_name, remote_dir))
                return False

            with open(local_file, 'rb') as f:
                # store file to remote path
                path_ = os.path.join(remote_dir, os.path.basename(local_file))
                self.conn.storeFile(svc_name, path_, f)
        except:
            return False
        
    def save_file(self, dat:bytes, svc_name, remote_file_path):
        try:
            remote_dir =  os.path.split(remote_file_path)[0]
            if not self.conn.getAttributes(svc_name, remote_dir).isDirectory:
                print("invalid remote path: {} - {}".format(svc_name, remote_dir))
                return False

            with io.BytesIO(dat) as f:
                f.seek(0)
                self.conn.storeFile(svc_name, remote_file_path, f)
        except OperationFailure as e:
            print(f)
            return False

        return True

    def exists(self, service_name, path):
        # parent = Path(path).parent.as_posix().replace('.', '/')
        # if parent == '/' or self.exists(service_name, parent):
        #     return bool([f for f in self.conn.listPath(service_name, parent) if f.filename == Path(path).name])
        target_path = Path(path)
        parent = Path(path).parent.as_posix()
        if parent == "/" or self.exists(service_name, parent):
            return bool(target_path.name in [f.filename for f in self.conn.listPath(service_name, parent)])
        else:
            return False


    def makedirs(self, service_name, path):
        parent = Path(path).parent.as_posix()
        if not parent == '/' and not self.exists(service_name, parent):
            self.makedirs(service_name, parent)
        if not self.exists(service_name, path):
            self.conn.createDirectory(service_name, path)


