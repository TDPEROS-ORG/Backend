import os

bind = "0.0.0.0:" + os.getenv("PORT", "8080")
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = 60
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
capture_output = True
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(L)s'