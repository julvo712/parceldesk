import json
from pathlib import Path
import tempfile
import unittest
from parceldesk_demo.development.events import DevelopmentLedger
from parceldesk_demo.telemetry import SnapshotTelemetry


class FakeExporter:
    def __init__(self):self.events=[];self.flushed=True
    def emit(self,event):self.events.append(event)
    def flush(self):return self.flushed


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.host=DevelopmentLedger(self.root/'host.sqlite')
        self.cache=DevelopmentLedger(self.root/'container.sqlite',publish_snapshots=False)
        self.exporter=FakeExporter();self.path=self.root/'telemetry-snapshot.json'
        self.consumer=SnapshotTelemetry(self.path,self.cache,self.root/'reports',self.exporter)
    def tearDown(self):self.host.close();self.cache.close();self.tmp.cleanup()
    def event(self):
        return {'event_id':'task-start','task_id':'task','event':'task_started',
                'actor':'test actor','evidence_ref':'test fixture','source_timestamp':'2026-09-15T13:00:00Z'}
    def test_mutation_publishes_complete_metrics_and_spool(self):
        self.host.append(self.event());value=json.loads(self.path.read_text())
        self.assertEqual(value['events'][0]['event_id'],'task-start')
        self.assertIn('parceldesk_development_tasks{state="incomplete"} 1',value['metrics'])
        self.assertEqual(self.host.db.execute('SELECT count(*) FROM events').fetchone()[0],1)
    def test_consumer_reads_without_host_database_and_acks_once(self):
        self.host.append(self.event());self.consumer.metrics_text();self.consumer.metrics_text()
        self.assertEqual(len(self.exporter.events),1)
        another=SnapshotTelemetry(self.path,self.cache,self.root/'reports',self.exporter)
        another.metrics_text();self.assertEqual(len(self.exporter.events),1)
        self.assertEqual(self.cache.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
    def test_failed_flush_keeps_spool_pending(self):
        self.host.append(self.event());self.exporter.flushed=False;self.consumer.flush_outbox()
        self.assertEqual(self.cache.db.execute('SELECT count(*) FROM development_spool_receipts').fetchone()[0],0)
        self.exporter.flushed=True;self.consumer.flush_outbox()
        self.assertEqual(self.cache.db.execute('SELECT count(*) FROM development_spool_receipts').fetchone()[0],1)
    def test_bad_snapshot_retains_known_values_with_visible_error(self):
        self.host.append(self.event());self.consumer.metrics_text();self.path.write_text('{partial')
        text=self.consumer.metrics_text()
        self.assertIn('parceldesk_development_snapshot_read_error 1',text)
        self.assertIn('parceldesk_development_tasks{state="incomplete"} 1',text)
    def test_missing_snapshot_does_not_invent_development_inventory(self):
        text=self.consumer.metrics_text();self.assertNotIn('parceldesk_development_tasks{',text)
        self.assertIn('parceldesk_development_snapshot_read_error 1',text)
    def test_container_cache_close_cannot_publish_host_snapshot(self):
        self.host.append(self.event());before=self.path.read_bytes()
        other=DevelopmentLedger(self.root/'another-cache.sqlite',publish_snapshots=False);other.close()
        self.assertEqual(before,self.path.read_bytes())


if __name__=='__main__':unittest.main()
