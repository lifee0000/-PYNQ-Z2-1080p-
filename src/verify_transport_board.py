"""Physical owner/cancellation/partial-frame tests against the V4 MMIO service."""
from pathlib import Path
import argparse,hashlib,json,socket,sys,time
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'native'))
from protocol import Session,Frame,Header,HELLO,FRAME,RESPONSE,PARAMETERS,read_json,parameter_words,status
from identity import load_identity
from codec import checksum,encode

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'evidence/board_transport.json')
    args=parser.parse_args()
    identity=load_identity(ROOT);cases=[]
    def idle():
        end=time.monotonic()+5
        while time.monotonic()<end:
            current=status()
            if current['state']=='IDLE':
                assert not current['first_fault'];return current
            assert current['state']=='OWNED',current
            time.sleep(.02)
        raise TimeoutError('Physical hardware owner retained after cancellation')
    def frames(n,w=1280,h=720):
        for i in range(n):yield Frame(i,i,bytes([31+i%200])*(w*h*2),{'mode':0})
    def opened():return Session(width=1280,height=720,expected_identity=identity)
    with opened():
        try:
            with opened():raise AssertionError('Owner stolen')
        except RuntimeError as exc:assert 'BUSY' in str(exc)
    idle();cases.append('BUSY_SINGLE_OWNER')
    sock=socket.create_connection(('192.168.2.99',5010),2)
    sock.sendall(Header(HELLO,width=1280,height=720).pack());read_json(sock,HELLO|RESPONSE)
    sock.sendall(Header(FRAME,0,0,1,50,1843200,PARAMETERS.size,1280,720).pack())
    sock.sendall(parameter_words(1280,720,{'mode':0}));sock.sendall(b'partial');sock.close()
    idle();cases.append('PARTIAL_INPUT_DISCONNECT_AND_RECOVERY')
    # Corrupt frames must be rejected before ANY DMA starts, on real hardware.
    raw=bytes([17])*384
    wire,flag,digest=encode(raw)
    malformed=[('RAW_CHECKSUM',raw,0,digest^1,'raw'),
               ('LZ4_CHECKSUM',wire,flag,digest^1,'lz4'),
               ('LZ4_TRUNCATED',b'\xf0\xff',1,digest,'lz4')]
    for name,payload,flags,digest,codec in malformed:
        before=idle()
        with socket.create_connection(('192.168.2.99',5010),3) as bad:
            bad.sendall(Header(HELLO,width=16,height=12,flags=int(codec=='lz4')).pack())
            read_json(bad,HELLO|RESPONSE)
            bad.sendall(Header(FRAME,1,1,1,50,len(payload),PARAMETERS.size,16,12,flags,digest).pack()+
                        parameter_words(16,12,{'mode':0})+payload)
            try:assert bad.recv(1)==b''
            except (ConnectionResetError,ConnectionAbortedError):pass
        after=idle()
        assert after['processed']==before['processed'] and after['received']==before['received']
        cases.append(name+'_REJECTED_BEFORE_DMA')
    import numpy as np
    random_raw=np.random.default_rng(20261024).integers(0,256,1843200,dtype=np.uint8).tobytes()
    for codec in ('raw','lz4'):
        with Session(width=1280,height=720,expected_identity=identity,max_inflight=1,wire_codec=codec) as full:
            values=list(full.exchange([Frame(1,1,random_raw,{'mode':0})]))
            assert values[0].payload==random_raw and values[0].completed_frames==1 and not values[0].stream_errors
            assert full.transport_metrics['compressed_input_frames']==0
        idle();cases.append('MAX_INCOMPRESSIBLE_EXACT_'+codec.upper())
    with opened() as session:
        results=session.exchange(frames(12));result=next(results)
        assert result.payload==bytes([31])*1843200
        results.close()
    idle();cases.append('INFLIGHT_CANCEL_AND_RECOVERY')
    with opened() as session:
        count=0
        for result in session.exchange(frames(10)):
            time.sleep(.05)
            assert result.frame_id==count
            assert result.payload==bytes([31+count])*1843200
            count+=1
        assert count==10
    final=idle();cases.append('SLOW_CONSUMER_10_UNIQUE_COMPLETE_720P_FRAMES')
    report=dict(status='PASS',evidence_kind='PHYSICAL_FPGA_TRANSPORT_AND_DMA_OWNERSHIP',
        identity=identity,cases=cases,final_status=final)
    args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(status='PASS',cases=cases)),flush=True)

if __name__=='__main__':main()
