import click
import random


@click.command('gen-secret-key')
def gen_secret_key_command():
    """Generate a secret key for Flask session"""
    click.echo(''.join([random.SystemRandom().choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)]))
