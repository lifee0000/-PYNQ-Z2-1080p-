"""Inert build/audit control with owned Jupyter-kernel cleanup; no FPGA setup."""
import os,uuid
from jupyter_link import JupyterClient,execute_code
def execute(code,timeout=145):
    client=JupyterClient('http://192.168.2.99:9090',10)
    specs=client.login(os.environ.get('PYNQ_JUPYTER_PASSWORD','xilinx'))
    kid=client.create_kernel(client.choose_kernel(specs,None));ws=None
    try:
        ws=client.connect_channels(kid,uuid.uuid4().hex,12)
        return execute_code(ws,code,timeout)
    finally:
        if ws is not None:ws.close()
        client.delete_kernel(kid)
