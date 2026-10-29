"""Build twice without cache and require identical local OCI image digests.

Defaults to the separate catalog image; pass --dockerfile/--image/--epoch for
the full Docker release. Neither build pushes to a registry.
"""
import argparse
import subprocess

IMAGE = 'ghcr.io/niklas-s04/aoostar-openscreen-catalog:1.0.2'


def main(image=IMAGE, dockerfile='Dockerfile.catalog', epoch='1793145600'):
    tags = [image, 'aoostar-image-repro:second']
    for tag in tags:
        subprocess.run([
            'docker', 'build', '--no-cache', '--build-arg', f'SOURCE_DATE_EPOCH={epoch}',
            '--provenance=false', '--output', 'type=docker,rewrite-timestamp=true',
            '--platform', 'linux/amd64', '-f', dockerfile, '-t', tag, '.',
        ], check=True)
    ids = subprocess.check_output(['docker', 'image', 'inspect', *tags, '--format', '{{.Id}}'], text=True).splitlines()
    assert len(ids) == 2 and ids[0] == ids[1], f'Non-reproducible image: {ids}'
    print('Two independent no-cache builds match:', ids[0])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default=IMAGE)
    parser.add_argument('--dockerfile', default='Dockerfile.catalog')
    parser.add_argument('--epoch', default='1793145600')
    args = parser.parse_args()
    main(args.image, args.dockerfile, args.epoch)
