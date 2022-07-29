"""Source for science-platform.png, an overview of the RSP architecture."""

import os

from diagrams import Cluster, Diagram
from diagrams.gcp.compute import KubernetesEngine
from diagrams.gcp.database import SQL
from diagrams.gcp.network import LoadBalancing
from diagrams.gcp.storage import Filestore, PersistentDisk
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.programming.framework import React

os.chdir(os.path.dirname(__file__))

graph_attr = {
    "label": "",
    "labelloc": "bbc",
    "nodesep": "0.2",
    "pad": "0.2",
    "ranksep": "0.75",
    "splines": "spline",
}

node_attr = {
    "fontsize": "12.0",
}

with Diagram(
    "Science Platform",
    show=False,
    filename="science-platform",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("End User")

    with Cluster("Science Platform"):
        ingress = LoadBalancing("ingress-nginx")

        with Cluster("Authentication"):
            ui = React("Gafaelfawr UI")
            gafaelfawr = KubernetesEngine("Gafaelfawr")
            storage = SQL("Database")
            redis = KubernetesEngine("Redis")
            redis_storage = PersistentDisk("Redis storage")

        with Cluster("Notebook Aspect"):
            hub = KubernetesEngine("Hub")
            session_storage = SQL("Session storage")
            lab = KubernetesEngine("Lab")

        with Cluster("API Aspect"):
            tap = KubernetesEngine("TAP")
            api = KubernetesEngine("Other API services")

        with Cluster("Science data storage"):
            filestore = Filestore("POSIX filesystem")
            qserv = SQL("qserv")
            butler = SQL("Butler")

        portal = KubernetesEngine("Portal Aspect")

    idp = Server("Identity provider")

    gafaelfawr >> idp
    user >> idp
    user >> ingress >> ui >> gafaelfawr >> redis >> redis_storage
    ingress >> gafaelfawr >> storage
    ingress << gafaelfawr
    ingress >> hub >> session_storage
    ingress >> lab >> filestore
    lab << hub
    lab >> butler
    ingress << lab
    ingress << portal
    ingress >> portal
    ingress >> api >> butler
    ingress << api
    ingress >> tap >> qserv
