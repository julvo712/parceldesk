"""Continuous process profiling; lifecycle belongs to the Uvicorn worker."""
import os


def start():
    endpoint = os.getenv('PYROSCOPE_SERVER_ADDRESS', '')
    if not endpoint:
        return None
    import pyroscope

    tags = {
        'service_name': 'parceldesk-agent',
        'service_namespace': 'parceldesk',
        'deployment_environment': os.getenv('DEPLOYMENT_ENVIRONMENT', 'demo-local'),
        'service_version': os.getenv('SERVICE_VERSION', 'development'),
    }
    for key, env in [('service_repository', 'SERVICE_REPOSITORY'), ('service_git_ref', 'GIT_COMMIT')]:
        if value := os.getenv(env):
            tags[key] = value
    # Python frames are rooted at /app/src; the repository keeps this package here.
    tags['service_root_path'] = 'apps/agent'
    pyroscope.configure(
        application_name='parceldesk-agent', server_address=endpoint,
        tags=tags, sample_rate=100, oncpu=True, gil_only=True,
        mem_enabled=True, enable_logging=True,
    )
    return pyroscope
