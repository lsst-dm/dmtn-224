"""Source for general-access.png component diagram."""

import os

from diagrams import Cluster, Diagram
from diagrams.gcp.compute import KubernetesEngine
from diagrams.gcp.database import SQL
from diagrams.gcp.network import LoadBalancing
from diagrams.gcp.storage import PersistentDisk
from diagrams.generic.storage import Storage
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.programming.framework import React

os.chdir(os.path.dirname(__file__))

graph_attr = {
    "label": "",
    "nodesep": "0.2",
    "pad": "0.2",
    "ranksep": "0.75",
    "splines": "spline",
}

node_attr = {
    "fontsize": "12.0",
}

with Diagram(
    "Federtaed identity deployment",
    show=False,
    filename="federated",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("End user")
    cilogon = Server("CILogon")
    comanage = Server("COmanage")
    ldap = Storage("COmanage LDAP")

    with Cluster("Science Platform deployment"):
        ingress = LoadBalancing("ingress-nginx")
        service = KubernetesEngine("Service")

        with Cluster("Gafaelfawr"):
            ui = React("Gafaelfawr UI")
            gafaelfawr = KubernetesEngine("Gafaelfawr")
            redis = KubernetesEngine("Redis")
            redis_storage = PersistentDisk("Redis storage")
            database = SQL("Database")

    user >> cilogon >> comanage >> ldap
    user >> comanage
    cilogon >> ldap
    user >> ingress >> service
    ingress << service
    ingress >> gafaelfawr >> database
    ingress >> ui >> gafaelfawr
    ingress << gafaelfawr
    gafaelfawr >> redis >> redis_storage
    gafaelfawr >> ldap
