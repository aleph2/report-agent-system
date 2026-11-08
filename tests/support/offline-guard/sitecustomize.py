import sys,ipaddress

def guard(event,args):
 if event=='socket.connect':
  addr=args[1]
  if isinstance(addr,tuple):
   host=str(addr[0])
   try:allowed=ipaddress.ip_address(host.split('%')[0]).is_loopback
   except ValueError:allowed=host=='localhost'
   if not allowed:raise RuntimeError('OFFLINE_TEST_EXTERNAL_NETWORK_FORBIDDEN')
 if event=='socket.getaddrinfo':
  host=args[0]
  if host is not None and str(host) not in {'localhost','127.0.0.1','::1','0.0.0.0',''}:
   raise RuntimeError('OFFLINE_TEST_EXTERNAL_DNS_FORBIDDEN')
sys.addaudithook(guard)

# Imported by file path in the parent guard and via PYTHONPATH in normal children.
import os
if os.environ.get('REPORT_STATE_CENSUS_DIR'):
    import runpy
    from pathlib import Path
    runpy.run_path(str(Path(__file__).with_name('state_trace.py')))['install'](os.environ['REPORT_STATE_CENSUS_DIR'])
