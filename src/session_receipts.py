"""Bind a kept video's final board release to its exact report and media bytes."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

SCHEMA = 1
RECEIPT_FIELD = 'board_release_receipt'
_UUID = re.compile(r'^[0-9a-f]{32}$')
_HASH = re.compile(r'^[0-9a-f]{64}$')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def report_digest(report):
    data = {k:v for k,v in report.items() if k != RECEIPT_FIELD}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                prefix='.'+path.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        for attempt in range(4):
            try:
                os.replace(temporary, path);temporary = None;break
            except PermissionError:
                if attempt == 3:raise
                time.sleep(.05*(2**attempt))
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def confirmed_stop(release):
    if not isinstance(release, dict) or release.get('status') != 'STOPPED_DMA_HALTED_CORE_RESET':return False
    if release.get('pid_gone') is not True or release.get('temporary_files_removed') is not True:return False
    if type(release.get('reset_gpio')) is not int or release['reset_gpio'] != 0:return False
    registers = release.get('registers') or {}
    names = ('mm2s_status','s2mm_status','mm2s_control','s2mm_control')
    if not all(type(registers.get(k)) is int for k in names):return False
    return bool(registers['mm2s_status']&1 and registers['s2mm_status']&1
        and not (registers['mm2s_control']&1 or registers['s2mm_control']&1))


def artifacts(video, trace):
    result = {}
    for label,path in (('video',Path(video)),('trace',Path(trace))):
        result[label] = dict(sha256=digest(path), bytes=path.stat().st_size) if path.is_file() else None
    return result


def validate_release_receipt(report, video, trace):
    """Content-bound proof only; caller still checks FPGA traces, identity and FPS."""
    issues = []
    session = report.get('board_session')
    receipt = report.get(RECEIPT_FIELD)
    if not isinstance(session,dict) or not isinstance(receipt,dict):return ['FINAL_RELEASE_RECEIPT_MISSING']
    if session.get('schema') != SCHEMA or receipt.get('schema') != SCHEMA:issues.append('RECEIPT_SCHEMA')
    owner = session.get('owner')
    if (not isinstance(owner,str) or not _UUID.fullmatch(owner) or session.get('session_id') != owner or
            receipt.get('owner') != owner or receipt.get('session_id') != owner):issues.append('RECEIPT_OWNER')
    if (not _UUID.fullmatch(str(session.get('report_id',''))) or
            receipt.get('report_id') != session.get('report_id')):issues.append('RECEIPT_REPORT_ID')
    if receipt.get('identity') != report.get('identity') or not receipt.get('identity'):issues.append('RECEIPT_IDENTITY')
    if not confirmed_stop(receipt.get('release')):issues.append('RECEIPT_STOP_NOT_CONFIRMED')
    try:
        if receipt.get('processing_report_sha256') != report_digest(report):issues.append('RECEIPT_REPORT_CHANGED')
        if receipt.get('artifacts') != artifacts(video,trace):issues.append('RECEIPT_MEDIA_CHANGED')
        if report.get('output_video_written'):
            item=(receipt.get('artifacts') or {}).get('video') or {}
            if not _HASH.fullmatch(str(report.get('output_sha256',''))) or item.get('sha256') != report['output_sha256']:
                issues.append('RECEIPT_VIDEO_HASH')
    except (OSError, ValueError, TypeError):issues.append('RECEIPT_CONTENT_UNREADABLE')
    return issues


class ReleaseJournal:
    """A window's reports and per-owner confirmed releases, including late registration."""
    def __init__(self):
        self.lock=threading.RLock();self.entries={};self.proofs={}

    @property
    def pending_count(self):
        with self.lock:return len(self.entries)

    def register(self, output, report, owner, identity):
        output=Path(output).resolve();path=Path(str(output)+'.json');trace=Path(str(output)+'.frames.jsonl')
        if not isinstance(owner,str) or not _UUID.fullmatch(owner):
            report['board_session']=dict(schema=SCHEMA,owner=None,role='ATTACHED_NOT_OWNED')
            write_json_atomic(path,report);return
        if report.get('identity') != identity:raise ValueError('Result identity differs from its board session')
        session=dict(schema=SCHEMA,owner=owner,session_id=owner,report_id=uuid.uuid4().hex)
        report['board_session']=session
        expected={}
        if report.get('output_video_written'):
            # run_video deliberately skips the export hash with tracing disabled.
            # Hash that completed file here, without enabling per-frame auditing.
            if report.get('trace_frames') is False and report.get('output_sha256') is None:
                report['output_sha256']=digest(output)
            if not output.is_file() or not _HASH.fullmatch(str(report.get('output_sha256',''))):
                raise ValueError('Completed export has no video hash or bytes')
            expected['video']=dict(sha256=report['output_sha256'],bytes=output.stat().st_size)
        else:expected['video']=None
        expected['trace']=dict(sha256=digest(trace),bytes=trace.stat().st_size) if trace.is_file() else None
        entry=dict(path=path,video=output,trace=trace,owner=owner,identity=deepcopy(identity),
            report_id=session['report_id'],report_sha256=report_digest(report),artifacts=expected)
        with self.lock:
            write_json_atomic(path,report);self.entries[session['report_id']]=entry
            # A close racing the writer may already have confirmed this owner.
            if owner in self.proofs:self._publish(entry,self.proofs[owner])

    def note_release(self, owner, identity, release):
        with self.lock:
            if confirmed_stop(release) and isinstance(owner,str) and _UUID.fullmatch(owner):
                self.proofs[owner]=dict(owner=owner,identity=deepcopy(identity),release=deepcopy(release),
                    released_utc=datetime.now(timezone.utc).isoformat())
            # A previous owner's receipt may have been temporarily locked at idle
            # release. A later service release must retry every confirmed owner.
            return self.flush()

    def _publish(self, entry, proof):
        if entry['identity'] != proof['identity']:raise ValueError('Release identity differs from the recorded owner')
        current=json.loads(entry['path'].read_text(encoding='utf-8'))
        if report_digest(current) != entry['report_sha256']:raise ValueError('Processing report changed after it was registered')
        if artifacts(entry['video'],entry['trace']) != entry['artifacts']:raise ValueError('Export or frame trace changed after processing')
        current[RECEIPT_FIELD]=dict(schema=SCHEMA,owner=entry['owner'],session_id=entry['owner'],report_id=entry['report_id'],
            identity=proof['identity'],released_utc=proof['released_utc'],release=proof['release'],
            processing_report_sha256=entry['report_sha256'],artifacts=entry['artifacts'])
        write_json_atomic(entry['path'],current);self.entries.pop(entry['report_id'],None)

    def flush(self, owner=None):
        with self.lock:
            written=0;errors=[]
            for entry in list(self.entries.values()):
                if owner is not None and entry['owner'] != owner:continue
                proof=self.proofs.get(entry['owner'])
                if proof is None:continue
                try:self._publish(entry,proof);written+=1
                except (OSError,ValueError,TypeError) as exc:
                    errors.append(dict(report=str(entry['path']),error=str(exc)))
            return dict(written=written,pending=len(self.entries),errors=errors)
