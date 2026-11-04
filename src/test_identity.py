"""Local build identity/provenance checks; no library, overlay or board access."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from identity import load_identity
from native.binding import ABI
from native.protocol import VERSION, PIXEL_FORMAT
from native.make_manifest import validate_arm_sources


class IdentityTests(unittest.TestCase):
    def test_current_identity_is_accepted_and_old_protocol_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roles = dict(bit_file='test.bit', hwh_file='test.hwh',
                         register_file='registers.json', native_library='library.so')
            for name in roles.values():
                (root/name).write_bytes(name.encode())
            files = {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                     for name in roles.values()}
            manifest = dict(schema=2, native_abi=ABI, protocol_version=VERSION,
                            state='EXPERIMENTAL_UNQUALIFIED',
                            top='video_enhance_yuyv422_v4_split_core',
                            pixel_format=PIXEL_FORMAT, files=files, **roles)
            path = root/'native_yuyv.experimental.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(load_identity(root)['bit_sha256'], files['test.bit'])
            for field, value in (('protocol_version', 6), ('native_abi', 4)):
                old = {**manifest, field: value}
                path.write_text(json.dumps(old), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Unsupported'):
                    load_identity(root)
            path.write_text(json.dumps(manifest), encoding='utf-8')
            (root/'library.so').write_bytes(b'wrong build')
            with self.assertRaisesRegex(ValueError, 'Build file mismatch'):
                load_identity(root)

    def test_arm_provenance_rejects_added_changed_and_removed_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'native').mkdir()
            source = root/'native/codec.cpp'
            source.write_bytes(b'original')
            record = {'source_sha256': {
                'native/codec.cpp': hashlib.sha256(source.read_bytes()).hexdigest()}}
            validate_arm_sources(root, record)
            header = root/'native/rice03_near_fast.h'
            header.write_bytes(b'new header absent in old ARM build')
            with self.assertRaisesRegex(ValueError, 'rice03_near_fast.h'):
                validate_arm_sources(root, record)
            header.unlink()
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'codec.cpp'):
                validate_arm_sources(root, record)
            source.unlink()
            with self.assertRaisesRegex(ValueError, 'codec.cpp'):
                validate_arm_sources(root, record)


if __name__ == '__main__':
    unittest.main()
