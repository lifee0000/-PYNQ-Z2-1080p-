"""Release evidence must survive reuse/relocation and reject wrong or changed data."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from session_receipts import ReleaseJournal, confirmed_stop, digest, validate_release_receipt, write_json_atomic

OWNER='a'*32
IDENTITY={'build':'unit-test-only'}


def stopped():
    return dict(status='STOPPED_DMA_HALTED_CORE_RESET',pid_gone=True,temporary_files_removed=True,reset_gpio=0,
        registers=dict(mm2s_status=1,s2mm_status=1,mm2s_control=0,s2mm_control=0))


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.journal=ReleaseJournal()
        self.video=self.root/'视频.mp4';self.video.write_bytes(b'video-bytes')
        self.trace=Path(str(self.video)+'.frames.jsonl');self.trace.write_bytes(b'frame-one\nframe-two\n')
        self.path=Path(str(self.video)+'.json')
        self.report=dict(status='PASS',identity=IDENTITY,frames=2,output_video_written=True,
            output_sha256=digest(self.video),trace_written=True,board_cleanup=dict(status='KEPT_FOR_NEXT_VIDEO'))

    def tearDown(self):self.temp.cleanup()
    def data(self):return json.loads(self.path.read_text(encoding='utf-8'))
    def register(self):self.journal.register(self.video,self.report,OWNER,IDENTITY)
    def release(self):return self.journal.note_release(OWNER,IDENTITY,stopped())
    def validate(self):return validate_release_receipt(self.data(),self.video,self.trace)

    def test_pending_is_not_a_confirmed_release(self):
        self.register();self.assertEqual(self.validate(),['FINAL_RELEASE_RECEIPT_MISSING'])

    def test_export_with_tracing_disabled_can_still_receive_its_stop_receipt(self):
        self.trace.unlink();self.report.update(trace_frames=False,trace_written=False,output_sha256=None)
        self.register();self.assertEqual(self.data()['output_sha256'],digest(self.video))
        self.release();self.assertEqual(self.validate(),[])
        self.assertIsNone(self.data()['board_release_receipt']['artifacts']['trace'])

    def test_missing_hash_on_an_audited_export_is_not_silently_repaired(self):
        self.report.update(trace_frames=True,output_sha256=None)
        with self.assertRaises(ValueError):self.register()

    def test_confirmed_release_keeps_original_processing_status(self):
        self.register();self.assertEqual(self.release()['written'],1)
        self.assertEqual(self.validate(),[])
        self.assertEqual(self.data()['board_cleanup']['status'],'KEPT_FOR_NEXT_VIDEO')

    def test_other_owner_cannot_release_this_report(self):
        self.register();self.journal.note_release('b'*32,IDENTITY,stopped())
        self.assertNotIn('board_release_receipt',self.data())
        self.release();self.assertEqual(self.validate(),[])

    def test_identity_mismatch_does_not_publish(self):
        self.register();result=self.journal.note_release(OWNER,{'build':'other'},stopped())
        self.assertEqual(len(result['errors']),1);self.assertNotIn('board_release_receipt',self.data())

    def test_unconfirmed_and_expired_without_register_proof_do_not_publish(self):
        self.register()
        for state in ('STOP_NOT_CONFIRMED','OWNED_RUNTIME_ALREADY_REMOVED'):
            self.journal.note_release(OWNER,IDENTITY,dict(status=state))
            self.assertNotIn('board_release_receipt',self.data())

    def test_missing_or_running_registers_do_not_confirm_stop(self):
        self.assertFalse(confirmed_stop(dict(status='STOPPED_DMA_HALTED_CORE_RESET')))
        bad=stopped();bad['registers']['mm2s_control']=1
        self.assertFalse(confirmed_stop(bad))
        bad=stopped();bad['reset_gpio']=1;self.assertFalse(confirmed_stop(bad))

    def test_video_changes_are_not_overwritten_with_a_valid_receipt(self):
        self.register();self.video.write_bytes(b'changed-video')
        self.assertEqual(len(self.release()['errors']),1);self.assertNotIn('board_release_receipt',self.data())

    def test_trace_changes_are_not_certified(self):
        self.register();self.trace.write_bytes(b'changed-trace')
        self.assertEqual(len(self.release()['errors']),1)

    def test_changed_report_is_preserved(self):
        self.register();data=self.data();data['frames']=20;write_json_atomic(self.path,data)
        self.assertEqual(len(self.release()['errors']),1)
        self.assertEqual(self.data()['frames'],20);self.assertNotIn('board_release_receipt',self.data())

    def test_receipt_cannot_be_swapped_between_reports(self):
        self.register();self.release();old=self.data()['board_release_receipt']
        self.journal.register(self.video,self.report,OWNER,IDENTITY)
        data=self.data();data['board_release_receipt']=old
        self.assertIn('RECEIPT_REPORT_ID',validate_release_receipt(data,self.video,self.trace))

    def test_portable_copy_does_not_require_original_absolute_paths(self):
        self.register();self.release();dest=self.root/'portable';dest.mkdir()
        for p in (self.video,self.trace,self.path):shutil.copy2(p,dest/p.name)
        data=json.loads((dest/self.path.name).read_text(encoding='utf-8'))
        self.assertEqual(validate_release_receipt(data,dest/self.video.name,dest/self.trace.name),[])

    def test_release_racing_late_registration_is_retained(self):
        self.release();self.register();self.assertEqual(self.validate(),[])

    def test_write_error_can_retry_without_changing_hardware_evidence(self):
        self.register()
        with mock.patch('session_receipts.write_json_atomic',side_effect=OSError('test write failure')):
            result=self.release()
        self.assertEqual(len(result['errors']),1);self.assertEqual(self.journal.pending_count,1)
        self.assertEqual(self.journal.flush()['written'],1);self.assertEqual(self.validate(),[])

    def test_owner_epochs_remain_independent(self):
        self.register();self.release()
        other=self.root/'other.mp4';other.write_bytes(b'other')
        report=deepcopy(self.report);report['output_sha256']=digest(other)
        self.journal.register(other,report,'b'*32,IDENTITY)
        self.assertNotIn('board_release_receipt',json.loads(Path(str(other)+'.json').read_text(encoding='utf-8')))
        self.journal.note_release('b'*32,IDENTITY,stopped())
        self.assertEqual(validate_release_receipt(json.loads(Path(str(other)+'.json').read_text(encoding='utf-8')),other,Path(str(other)+'.frames.jsonl')),[])

    def test_new_owner_release_retries_previous_confirmed_owner_write(self):
        self.register()
        with mock.patch('session_receipts.write_json_atomic',side_effect=PermissionError('temporarily locked')):
            self.assertEqual(len(self.release()['errors']),1)
        other=self.root/'new-owner.mp4';other.write_bytes(b'new owner')
        report=deepcopy(self.report);report['output_sha256']=digest(other)
        self.journal.register(other,report,'b'*32,IDENTITY)
        result=self.journal.note_release('b'*32,IDENTITY,stopped())
        self.assertEqual(result,dict(written=2,pending=0,errors=[]))
        self.assertEqual(self.validate(),[])

    def test_attached_service_cannot_claim_owned_release(self):
        self.journal.register(self.video,self.report,None,IDENTITY)
        self.release();self.assertEqual(self.validate(),['FINAL_RELEASE_RECEIPT_MISSING'])

    def test_atomic_write_failure_leaves_original_and_no_temporary_file(self):
        self.register();before=self.path.read_bytes()
        with mock.patch('session_receipts.os.replace',side_effect=PermissionError('test locked file')),mock.patch('session_receipts.time.sleep'):
            with self.assertRaises(PermissionError):write_json_atomic(self.path,{'changed':True})
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(list(self.root.glob('*.tmp')),[])


if __name__=='__main__':unittest.main()
