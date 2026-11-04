import json,sys,traceback
from pathlib import Path

def main():
    if '--compare-check' in sys.argv:
        from preview_compare_validation import check
        report=check(Path(sys.argv[sys.argv.index('--compare-check')+1]))
        raise SystemExit(0 if report['status']=='PASS' else 1)
    elif '--image-controls-check' in sys.argv:
        from image_controls_validation import check
        report=check(Path(sys.argv[sys.argv.index('--image-controls-check')+1]))
        raise SystemExit(0 if report['status']=='PASS' else 1)
    elif '--gui-acceptance' in sys.argv:
        from gui_acceptance import run as acceptance
        i=sys.argv.index('--gui-acceptance')
        report=acceptance(sys.argv[i+1],Path(sys.argv[i+2]),sys.argv[i+3:])
        raise SystemExit(0 if report['status']=='PASS' else 1)
    elif '--physical-ui-check' in sys.argv:
        from physical_ui_validation import run
        run(Path(sys.argv[sys.argv.index('--physical-ui-check')+1]),Path(sys.argv[sys.argv.index('--ui-input')+1]))
    elif '--ui-check' in sys.argv:
        from ui_validation import check
        target=Path(sys.argv[sys.argv.index('--ui-check')+1])
        fixtures=Path(sys.argv[sys.argv.index('--ui-fixtures')+1])
        check(target,fixtures)
    elif '--self-test' in sys.argv:
        from identity import load_identity
        from native.protocol import parameter_words,PARAMETERS
        from run_video import ROOT
        from offline_video import process as offline_process
        from pixels import pack_rgb,unpack_rgb,FORMAT_BACKEND
        from native.codec import encode,decode,codec_info
        import numpy as np
        from native_pixels_bridge import STATISTICS_AVAILABLE
        from exposure_v4 import analyze_yuyv_v4
        from auto_v5 import AUTO_POLICY_V5
        from image_controls import ImageControls, apply_controls
        from native.protocol import DEFAULTS
        controls=ImageControls(preset='balanced',brightness=12,denoise=40,sharpen=50,clarity=20,color_preservation=80)
        controlled=apply_controls(dict(DEFAULTS),controls,automatic=True)
        assert len(parameter_words(1920,1080,controlled))==96 and controlled['sharp_q8_8']==512 and controlled['chroma_q8']==205
        assert apply_controls(dict(DEFAULTS),ImageControls())==DEFAULTS
        import ssl
        from board_link import ManagedBoard
        ssl.create_default_context()
        board=ManagedBoard()  # Constructor only, no network connection.
        sample=np.full((3,4,3),128,np.uint8)
        assert pack_rgb(sample)==bytes([128,128])*(3*4)
        assert np.array_equal(unpack_rgb(pack_rgb(sample),4,3),sample)
        raw=bytes(range(256))*100
        wire,flag,digest=encode(raw)
        assert decode(wire,flag,len(raw),digest)==raw
        from native.rice_codec import adaptive_encode,decode as rice_decode
        near_checks=[]
        for w,h in ((1280,720),(1920,1080)):
            rice_raw=bytes([64,128,64,128])*(w*h//2)
            rice_wire,rice_flag,rice_hash=adaptive_encode(rice_raw,w,h)
            assert rice_flag==3 and rice_decode(rice_wire,rice_flag,len(rice_raw),rice_hash)==rice_raw
            near_raw=bytes(range(256))*(w*h//128)
            for shift in (2,3):
                wire,flag,digest=adaptive_encode(near_raw,w,h,shift)
                restored=rice_decode(wire,flag,len(near_raw),digest)
                maximum=int(np.abs(np.frombuffer(restored,np.uint8).astype(np.int16)-np.frombuffer(near_raw,np.uint8)).max())
                assert maximum<=(1<<(shift-1))
                near_checks.append(dict(geometry=[w,h],near_shift=shift,maximum_error=maximum,wire_codec_flag=flag))
            assert STATISTICS_AVAILABLE
            stats,_=analyze_yuyv_v4(rice_raw,w,h)
            assert stats['mean_q8']==64*256
        result=dict(status='PASS',identity=load_identity(ROOT),parameter_bytes=len(parameter_words(1920,1080)),
            av_imported=True,offline_imported=callable(offline_process),no_board_connection=True,
            image_controls=True,image_control_schema=1,
            algorithm_policy=AUTO_POLICY_V5,
            format_conversion_backend=FORMAT_BACKEND,format_conversion_smoke=True,
            ssl_context_smoke=True,jupyter_client_constructed=board.owned is None,
            lossless_codec=codec_info(),lossless_roundtrip=True,p6_rice03_full720_roundtrip=True,p6_rice03_full1080_roundtrip=True,near_codec_checks=near_checks,native_statistics=True,protocol_version=7)
        # 24 parameters (enhance IP 1.5 adds clarity); checked before PASS is written.
        assert result['parameter_bytes']==96
        from preview_compare import load_samples
        samples=load_samples()
        assert len(samples)==6
        result.update(comparison_view=True,comparison_samples=len(samples))
        target=Path(sys.argv[sys.argv.index('--self-test')+1]);target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    elif '--offline' in sys.argv:
        sys.argv.remove('--offline')
        from offline_video import main
        raise SystemExit(main())
    elif '--input' in sys.argv:
        from run_video import main
        main()
    else:
        from gui import main
        main()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        if not any(x in sys.argv for x in ('--input','--self-test','--ui-check','--physical-ui-check','--gui-acceptance','--image-controls-check','--compare-check')):raise
        if '--gui-acceptance' in sys.argv:
            # Unattended runs: an uncaught error in the windowed EXE would wait on a dialog.
            i=sys.argv.index('--gui-acceptance');path=Path(sys.argv[i+2])/sys.argv[i+1]
        else:
            flag='--compare-check' if '--compare-check' in sys.argv else '--image-controls-check' if '--image-controls-check' in sys.argv else '--output' if '--output' in sys.argv else '--self-test' if '--self-test' in sys.argv else '--physical-ui-check' if '--physical-ui-check' in sys.argv else '--ui-check'
            path=Path(sys.argv[sys.argv.index(flag)+1])
        path.parent.mkdir(parents=True,exist_ok=True)
        path.with_name(path.name+'.launch_error.json').write_text(json.dumps(dict(
            status='FAIL',error=str(exc),traceback=traceback.format_exc()),indent=2),encoding='utf-8')
        raise SystemExit(1)
