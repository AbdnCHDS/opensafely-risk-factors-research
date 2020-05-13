import subprocess
import docker
import os

client = docker.from_env()


def run(cmd, detach=False):
    return client.containers.run(
        "stata-mp",
        cmd,
        detach=detach,
        working_dir="/tmp",
        mounts=[docker.types.Mount("/tmp", os.getcwd(), type="bind")],
    )


# this seems to work, although input.csv is empty, so...
asd = run("cr_create_analysis_dataset.do")
import pdb

pdb.set_trace()
c = 5
