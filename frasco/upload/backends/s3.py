from flask import current_app, g
from frasco.ext import get_extension_state, has_extension
from frasco.upload.backend import StorageBackend, RemoteOpenStorageBackendMixin
from frasco.upload.utils import save_uploaded_file_temporarly, generate_filename
from frasco.tasks import enqueue_task
import boto3
import os
import urllib.request, urllib.parse, urllib.error


AWS_CLIENT_OPTIONS = ('aws_access_key_id', 'aws_secret_access_key',
                        'aws_session_token', 'region_name', 'endpoint_url',
                        'config')


class S3StorageBackend(RemoteOpenStorageBackendMixin, StorageBackend):
    default_options = {'filename_prefix': '',
                       'acl': 'public-read',
                       'async': False,
                       'signed_url': False,
                       'signed_url_ttl': 3600,
                       'set_content_disposition_header_with_filename': True,
                       'ignore_images_content_disposition_header': True,
                       'charset': None}

    def save(self, file, filename, force_sync=False):
        kwargs = dict(filename=filename, content_disposition_filename=file.filename,
            bucket=self.options.get('bucket'), acl=self.options['acl'],
            prefix=self.options['filename_prefix'], backend=self.name)

        if not force_sync and self.options.get('async') and has_extension('frasco_tasks'):
            tmpname = save_uploaded_file_temporarly(file, filename)
            enqueue_task(upload_file_to_s3, stream_or_filename=tmpname, mimetype=file.mimetype,
                delete_source=True, **kwargs)
        else:
            upload_file_to_s3(file, **kwargs)

    def url_for(self, filename, **kwargs):
        bucket = self.options.get('bucket')
        if self.options['signed_url']:
            client = get_s3_client(self.name)
            return client.generate_presigned_url('get_object',
                Params={'Bucket': bucket, 'Key': filename},
                ExpiresIn=self.options['signed_url_ttl'])
        return 'https://%s.s3.amazonaws.com/%s' % (bucket, filename)

    def delete(self, filename, force_sync=False):
        if not force_sync and self.options['async'] and has_extension('frasco_tasks'):
            enqueue_task('delete_s3_file', filename=filename, backend=self.name)
        else:
            delete_s3_file(filename, backend=self.name)


def get_s3_options(backend=None):
    return get_extension_state('frasco_upload').get_backend(backend or 's3').options


def get_s3_client(backend=None, use_cached=True):
    if use_cached and "boto_s3_client" in g:
        return g.boto_s3_client
    
    options = get_s3_options(backend)
    kwargs = {}
    if options.get('access_key'):
        kwargs['aws_access_key_id'] = options['access_key']
    if options.get('secret_key'):
        kwargs['aws_secret_access_key'] = options['secret_key']
    for k in AWS_CLIENT_OPTIONS:
        if options.get(k):
            kwargs[k] = options[k]

    client = boto3.client('s3', **kwargs)
    if use_cached:
        g.boto_s3_client = client
    return client


def get_s3_bucket_and_object(filename, backend=None, bucket=None, prefix=None):
    options = get_s3_options(backend)
    if not bucket:
        assert 'bucket' in options, "Missing bucket option"
        bucket = options['bucket']
    prefix = prefix or options['filename_prefix']
    return bucket, prefix + filename


def _generate_object_headers(filename, mimetype=None, charset=None, content_disposition_filename=None, backend=None):
    options = get_s3_options(backend)
    headers = {}

    set_content_disposition = options['set_content_disposition_header_with_filename']
    if options['ignore_images_content_disposition_header'] and mimetype and mimetype.startswith('image/'):
        set_content_disposition = False
    if set_content_disposition:
        if not content_disposition_filename:
            content_disposition_filename = filename
        if isinstance(content_disposition_filename, str):
            content_disposition_filename = content_disposition_filename.encode("utf-8")
        headers['Content-Disposition'] = 'attachment;filename="%s"' % urllib.parse.quote(content_disposition_filename)

    if mimetype:
        headers['Content-Type'] = mimetype

    if charset or options['charset']:
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'binary/octet-stream' # S3 default mimetype
        headers['Content-Type'] += '; charset=%s' % (charset or options['charset'])

    return headers


def upload_file_to_s3(stream_or_filename, filename, bucket=None, prefix=None,
                      acl=None, delete_source=False, backend=None, **object_headers_options):
    options = get_s3_options(backend)
    client = get_s3_client(backend)
    bucket, object_name = get_s3_bucket_and_object(filename, backend, bucket, prefix)
    extra_args = {}

    acl = acl or options['acl']
    if acl:
        extra_args['ACL'] = acl

    extra_args.update({k.replace('-', ''): v for k, v in \
        list(_generate_object_headers(filename, backend=backend, **object_headers_options).items())})

    is_filename = isinstance(stream_or_filename, str)
    if is_filename:
        client.upload_file(stream_or_filename, bucket, object_name, ExtraArgs=extra_args)
    else:
        client.upload_fileobj(stream_or_filename, bucket, object_name, ExtraArgs=extra_args)

    if is_filename and delete_source:
        os.unlink(stream_or_filename)


def generate_s3_presigned_upload_url(max_file_size=None, expires_in=3600, bucket=None, prefix=None, acl=None, backend=None):
    options = get_s3_options(backend)
    client = get_s3_client(backend)
    filename = generate_filename('${filename}')
    bucket, object_name = get_s3_bucket_and_object(filename, backend, bucket, prefix)
    fields = {}
    conditions = []

    acl = acl or options['acl']
    if acl:
        fields['acl'] = acl
        conditions.append({'acl': acl})

    if max_file_size:
        conditions.append(["content-length-range", 1, max_file_size])

    r = client.generate_presigned_post(bucket, object_name, fields, conditions, expires_in)
    return r['url'], r['fields']


def delete_s3_file(filename, bucket=None, prefix=None, backend=None):
    client = get_s3_client(backend)
    bucket, object_name = get_s3_bucket_and_object(filename, backend, bucket, prefix)
    client.delete_object(bucket, object_name)
