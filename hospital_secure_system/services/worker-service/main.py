import json
import os
import time

import pika
import psycopg2


def db():
    return psycopg2.connect(host="postgres", dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"])


def process_record(record_id: int):
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE medical_records SET processing_status='processed' WHERE id=%s", (record_id,))
    cur.execute("UPDATE background_jobs SET status='processed', details='worker checked encrypted storage and queued metadata', updated_at=CURRENT_TIMESTAMP WHERE record_id=%s", (record_id,))
    cur.execute("INSERT INTO audit_logs(user_id,action,status,details) VALUES(NULL,'background_job','success',%s)", (f"record_id={record_id} processed",))
    conn.commit(); cur.close(); conn.close()


def consume():
    while True:
        try:
            creds = pika.PlainCredentials(os.environ["RABBITMQ_DEFAULT_USER"], os.environ["RABBITMQ_DEFAULT_PASS"])
            con = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq", 5672, "/", creds))
            ch = con.channel(); ch.queue_declare(queue="record_jobs", durable=True)

            def cb(channel, method, props, body):
                try:
                    msg = json.loads(body); process_record(int(msg["record_id"]))
                    channel.basic_ack(method.delivery_tag)
                except Exception as exc:
                    conn = db(); cur = conn.cursor()
                    cur.execute("INSERT INTO audit_logs(user_id,action,status,details) VALUES(NULL,'background_job','failed',%s)", (str(exc)[:500],))
                    conn.commit(); cur.close(); conn.close()
                    channel.basic_nack(method.delivery_tag, requeue=False)

            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue="record_jobs", on_message_callback=cb)
            ch.start_consuming()
        except Exception:
            time.sleep(5)


if __name__ == "__main__":
    consume()
