"""Test Kubernetes tools with mocked kubernetes client."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from mcp_hub.tools.k8s_tools import (
    get_cluster_status,
    get_deployments,
    get_namespace_pods,
    get_services,
    list_namespaces,
)


def _mock_node(name, ready="True", roles=None, cpu="4", memory="8Gi"):
    """Build a mock Kubernetes node object."""
    node = MagicMock()
    node.metadata.name = name
    labels = {}
    for role in roles or []:
        labels[f"node-role.kubernetes.io/{role}"] = ""
    node.metadata.labels = labels
    ready_cond = MagicMock()
    ready_cond.type = "Ready"
    ready_cond.status = ready
    node.status.conditions = [ready_cond]
    node.status.capacity = {"cpu": cpu, "memory": memory}
    return node


def _mock_namespace(name, phase="Active", created="2026-01-15T00:00:00Z"):
    ns = MagicMock()
    ns.metadata.name = name
    ns.status.phase = phase
    ns.metadata.creation_timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
    return ns


def _mock_pod(name, phase="Running", restart_counts=None):
    pod = MagicMock()
    pod.metadata.name = name
    pod.status.phase = phase
    if restart_counts is not None:
        statuses = []
        for count in restart_counts:
            cs = MagicMock()
            cs.restart_count = count
            statuses.append(cs)
        pod.status.container_statuses = statuses
    else:
        pod.status.container_statuses = []
    return pod


def _mock_service(namespace, name, svc_type="ClusterIP", ports=None, ingress_ips=None):
    svc = MagicMock()
    svc.metadata.namespace = namespace
    svc.metadata.name = name
    svc.spec.type = svc_type
    if ports:
        mock_ports = []
        for port, protocol in ports:
            p = MagicMock()
            p.port = port
            p.protocol = protocol
            mock_ports.append(p)
        svc.spec.ports = mock_ports
    else:
        svc.spec.ports = []
    if ingress_ips:
        ingress_objs = []
        for ip in ingress_ips:
            ing = MagicMock()
            ing.ip = ip
            ingress_objs.append(ing)
        svc.status.load_balancer.ingress = ingress_objs
    else:
        svc.status.load_balancer = MagicMock()
        svc.status.load_balancer.ingress = None
    return svc


def _mock_deployment(namespace, name, ready_replicas=2, desired_replicas=3):
    dep = MagicMock()
    dep.metadata.namespace = namespace
    dep.metadata.name = name
    dep.status.ready_replicas = ready_replicas
    dep.spec.replicas = desired_replicas
    return dep


@pytest.fixture
def mock_k8s_client():
    """Patch _get_k8s_client to return a mock kubernetes client module."""
    with patch("mcp_hub.tools.k8s_tools._get_k8s_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        yield client


@pytest.fixture
def mock_run_sync():
    """Patch _run_sync to directly call the sync function (no threading)."""
    with patch("mcp_hub.tools.k8s_tools._run_sync") as mock_rs:

        async def call_func(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_rs.side_effect = call_func
        yield mock_rs


# ---------- get_cluster_status ----------


@pytest.mark.asyncio
async def test_get_cluster_status_single_node(mock_k8s_client, mock_run_sync):
    node = _mock_node(
        "control-plane",
        ready="True",
        roles=["control-plane"],
        cpu="8",
        memory="16Gi",
    )
    mock_k8s_client.CoreV1Api().list_node.return_value.items = [node]

    result = await get_cluster_status()
    assert "## Cluster Nodes" in result
    assert "control-plane" in result
    assert "Ready: True" in result
    assert "CPU: 8" in result
    assert "Memory: 16Gi" in result
    assert "control-plane" in result


@pytest.mark.asyncio
async def test_get_cluster_status_multiple_nodes(mock_k8s_client, mock_run_sync):
    nodes = [
        _mock_node("master-01", roles=["control-plane"], cpu="4", memory="8Gi"),
        _mock_node("worker-01", roles=[], cpu="8", memory="32Gi"),
        _mock_node("worker-02", roles=[], cpu="8", memory="32Gi"),
    ]
    mock_k8s_client.CoreV1Api().list_node.return_value.items = nodes

    result = await get_cluster_status()
    assert "master-01" in result
    assert "worker-01" in result
    assert "worker-02" in result


@pytest.mark.asyncio
async def test_get_cluster_status_no_roles_shows_worker(mock_k8s_client, mock_run_sync):
    node = _mock_node("bare-node", roles=[])
    mock_k8s_client.CoreV1Api().list_node.return_value.items = [node]

    result = await get_cluster_status()
    assert "worker" in result


@pytest.mark.asyncio
async def test_get_cluster_status_not_ready(mock_k8s_client, mock_run_sync):
    node = _mock_node("sick-node", ready="False", roles=["control-plane"])
    mock_k8s_client.CoreV1Api().list_node.return_value.items = [node]

    result = await get_cluster_status()
    assert "Ready: False" in result


@pytest.mark.asyncio
async def test_get_cluster_status_empty_cluster(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_node.return_value.items = []

    result = await get_cluster_status()
    assert "## Cluster Nodes" in result


@pytest.mark.asyncio
async def test_get_cluster_status_api_error(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_node.side_effect = Exception("connection refused")

    with pytest.raises(Exception, match="connection refused"):
        await get_cluster_status()


# ---------- list_namespaces ----------


@pytest.mark.asyncio
async def test_list_namespaces_with_results(mock_k8s_client, mock_run_sync):
    namespaces = [
        _mock_namespace("default", "Active"),
        _mock_namespace("kube-system", "Active"),
        _mock_namespace("monitoring", "Active"),
    ]
    mock_k8s_client.CoreV1Api().list_namespace.return_value.items = namespaces

    result = await list_namespaces()
    assert "## Namespaces" in result
    assert "default" in result
    assert "kube-system" in result
    assert "monitoring" in result
    assert "Active" in result


@pytest.mark.asyncio
async def test_list_namespaces_shows_creation_date(mock_k8s_client, mock_run_sync):
    ns = _mock_namespace("test-ns", created="2026-03-15T10:30:00Z")
    mock_k8s_client.CoreV1Api().list_namespace.return_value.items = [ns]

    result = await list_namespaces()
    assert "2026-03-15" in result


@pytest.mark.asyncio
async def test_list_namespaces_empty(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_namespace.return_value.items = []

    result = await list_namespaces()
    assert "## Namespaces" in result


@pytest.mark.asyncio
async def test_list_namespaces_api_error(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_namespace.side_effect = Exception("unauthorized")

    with pytest.raises(Exception, match="unauthorized"):
        await list_namespaces()


# ---------- get_namespace_pods ----------


@pytest.mark.asyncio
async def test_get_namespace_pods_default(mock_k8s_client, mock_run_sync):
    pods = [
        _mock_pod("nginx-abc123", "Running", [0]),
        _mock_pod("redis-def456", "Running", [2]),
    ]
    mock_k8s_client.CoreV1Api().list_namespaced_pod.return_value.items = pods

    result = await get_namespace_pods()
    assert "## Pods in default" in result
    assert "nginx-abc123" in result
    assert "restarts: 0" in result
    assert "redis-def456" in result
    assert "restarts: 2" in result


@pytest.mark.asyncio
async def test_get_namespace_pods_custom_namespace(mock_k8s_client, mock_run_sync):
    pod = _mock_pod("grafana-xyz", "Running", [0])
    mock_k8s_client.CoreV1Api().list_namespaced_pod.return_value.items = [pod]

    result = await get_namespace_pods(namespace="monitoring")
    assert "## Pods in monitoring" in result
    assert "grafana-xyz" in result


@pytest.mark.asyncio
async def test_get_namespace_pods_empty(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_namespaced_pod.return_value.items = []

    result = await get_namespace_pods(namespace="empty-ns")
    assert "No pods found in namespace empty-ns" in result


@pytest.mark.asyncio
async def test_get_namespace_pods_multiple_containers(mock_k8s_client, mock_run_sync):
    pod = _mock_pod("sidecar-pod", "Running", [3, 1, 0])
    mock_k8s_client.CoreV1Api().list_namespaced_pod.return_value.items = [pod]

    result = await get_namespace_pods()
    assert "restarts: 4" in result


@pytest.mark.asyncio
async def test_get_namespace_pods_no_container_statuses(mock_k8s_client, mock_run_sync):
    pod = MagicMock()
    pod.metadata.name = "pending-pod"
    pod.status.phase = "Pending"
    pod.status.container_statuses = None
    mock_k8s_client.CoreV1Api().list_namespaced_pod.return_value.items = [pod]

    result = await get_namespace_pods()
    assert "pending-pod" in result
    assert "restarts: 0" in result


@pytest.mark.asyncio
async def test_get_namespace_pods_crashloop(mock_k8s_client, mock_run_sync):
    pod = _mock_pod("crash-pod", "CrashLoopBackOff", [15])
    mock_k8s_client.CoreV1Api().list_namespaced_pod.return_value.items = [pod]

    result = await get_namespace_pods()
    assert "CrashLoopBackOff" in result
    assert "restarts: 15" in result


@pytest.mark.asyncio
async def test_get_namespace_pods_api_error(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_namespaced_pod.side_effect = Exception("forbidden")

    with pytest.raises(Exception, match="forbidden"):
        await get_namespace_pods(namespace="restricted")


# ---------- get_services ----------


@pytest.mark.asyncio
async def test_get_services_all_namespaces(mock_k8s_client, mock_run_sync):
    services = [
        _mock_service("default", "kubernetes", "ClusterIP", [(443, "TCP")]),
        _mock_service("monitoring", "prometheus", "ClusterIP", [(9090, "TCP")]),
    ]
    mock_k8s_client.CoreV1Api().list_service_for_all_namespaces.return_value.items = services

    result = await get_services()
    assert "## Services" in result
    assert "default/kubernetes" in result
    assert "monitoring/prometheus" in result
    assert "443/TCP" in result
    assert "9090/TCP" in result


@pytest.mark.asyncio
async def test_get_services_filtered_namespace(mock_k8s_client, mock_run_sync):
    svc = _mock_service("monitoring", "grafana", "NodePort", [(3000, "TCP")])
    mock_k8s_client.CoreV1Api().list_namespaced_service.return_value.items = [svc]

    result = await get_services(namespace="monitoring")
    assert "monitoring/grafana" in result
    assert "NodePort" in result
    mock_k8s_client.CoreV1Api().list_namespaced_service.assert_called_once_with(
        namespace="monitoring"
    )


@pytest.mark.asyncio
async def test_get_services_loadbalancer_with_external_ip(mock_k8s_client, mock_run_sync):
    svc = _mock_service(
        "ingress",
        "traefik",
        "LoadBalancer",
        [(80, "TCP"), (443, "TCP")],
        ingress_ips=["192.168.40.200"],
    )
    mock_k8s_client.CoreV1Api().list_service_for_all_namespaces.return_value.items = [svc]

    result = await get_services()
    assert "LoadBalancer" in result
    assert "external: 192.168.40.200" in result
    assert "80/TCP" in result
    assert "443/TCP" in result


@pytest.mark.asyncio
async def test_get_services_no_ports(mock_k8s_client, mock_run_sync):
    svc = _mock_service("default", "headless-svc", "ClusterIP", ports=None)
    mock_k8s_client.CoreV1Api().list_service_for_all_namespaces.return_value.items = [svc]

    result = await get_services()
    assert "headless-svc" in result


@pytest.mark.asyncio
async def test_get_services_multiple_external_ips(mock_k8s_client, mock_run_sync):
    svc = _mock_service(
        "ingress",
        "lb-svc",
        "LoadBalancer",
        [(80, "TCP")],
        ingress_ips=["10.0.0.1", "10.0.0.2"],
    )
    mock_k8s_client.CoreV1Api().list_service_for_all_namespaces.return_value.items = [svc]

    result = await get_services()
    assert "10.0.0.1" in result
    assert "10.0.0.2" in result


@pytest.mark.asyncio
async def test_get_services_api_error(mock_k8s_client, mock_run_sync):
    mock_k8s_client.CoreV1Api().list_service_for_all_namespaces.side_effect = Exception("timeout")

    with pytest.raises(Exception, match="timeout"):
        await get_services()


# ---------- get_deployments ----------


@pytest.mark.asyncio
async def test_get_deployments_all_namespaces(mock_k8s_client, mock_run_sync):
    deps = [
        _mock_deployment("default", "nginx", 3, 3),
        _mock_deployment("monitoring", "prometheus", 1, 1),
    ]
    mock_k8s_client.AppsV1Api().list_deployment_for_all_namespaces.return_value.items = deps

    result = await get_deployments()
    assert "## Deployments" in result
    assert "default/nginx" in result
    assert "3/3 ready" in result
    assert "monitoring/prometheus" in result
    assert "1/1 ready" in result


@pytest.mark.asyncio
async def test_get_deployments_filtered_namespace(mock_k8s_client, mock_run_sync):
    dep = _mock_deployment("apps", "web-app", 2, 3)
    mock_k8s_client.AppsV1Api().list_namespaced_deployment.return_value.items = [dep]

    result = await get_deployments(namespace="apps")
    assert "apps/web-app" in result
    assert "2/3 ready" in result
    mock_k8s_client.AppsV1Api().list_namespaced_deployment.assert_called_once_with(namespace="apps")


@pytest.mark.asyncio
async def test_get_deployments_zero_ready_replicas(mock_k8s_client, mock_run_sync):
    dep = _mock_deployment("default", "broken-app", ready_replicas=None, desired_replicas=2)
    # ready_replicas=None maps to 0 in the code
    dep.status.ready_replicas = None
    mock_k8s_client.AppsV1Api().list_deployment_for_all_namespaces.return_value.items = [dep]

    result = await get_deployments()
    assert "0/2 ready" in result


@pytest.mark.asyncio
async def test_get_deployments_zero_desired_replicas(mock_k8s_client, mock_run_sync):
    dep = _mock_deployment("default", "scaled-down", ready_replicas=0, desired_replicas=None)
    dep.status.ready_replicas = 0
    dep.spec.replicas = None
    mock_k8s_client.AppsV1Api().list_deployment_for_all_namespaces.return_value.items = [dep]

    result = await get_deployments()
    assert "0/0 ready" in result


@pytest.mark.asyncio
async def test_get_deployments_empty(mock_k8s_client, mock_run_sync):
    mock_k8s_client.AppsV1Api().list_deployment_for_all_namespaces.return_value.items = []

    result = await get_deployments()
    assert "## Deployments" in result


@pytest.mark.asyncio
async def test_get_deployments_api_error(mock_k8s_client, mock_run_sync):
    mock_k8s_client.AppsV1Api().list_deployment_for_all_namespaces.side_effect = Exception(
        "api server unreachable"
    )

    with pytest.raises(Exception, match="api server unreachable"):
        await get_deployments()


# ---------- _get_k8s_client ----------


def test_get_k8s_client_with_kube_config():
    """When settings.kube_config is set, load_kube_config uses that path."""
    mock_config = MagicMock()
    mock_client = MagicMock()
    mock_k8s = MagicMock(client=mock_client, config=mock_config)

    with (
        patch("mcp_hub.tools.k8s_tools.settings") as mock_settings,
        patch.dict(
            "sys.modules",
            {
                "kubernetes": mock_k8s,
                "kubernetes.client": mock_client,
                "kubernetes.config": mock_config,
            },
        ),
    ):
        mock_settings.kube_config = "/path/to/kubeconfig"
        from mcp_hub.tools.k8s_tools import _get_k8s_client

        _get_k8s_client()
        mock_config.load_kube_config.assert_called_once_with(config_file="/path/to/kubeconfig")


def test_get_k8s_client_incluster_fallback():
    """When no kube_config, try incluster first, then default kubeconfig."""
    mock_config = MagicMock()
    mock_config.ConfigException = Exception
    mock_config.load_incluster_config.side_effect = Exception("not in cluster")
    mock_client = MagicMock()
    mock_k8s = MagicMock(client=mock_client, config=mock_config)

    with (
        patch("mcp_hub.tools.k8s_tools.settings") as mock_settings,
        patch.dict(
            "sys.modules",
            {
                "kubernetes": mock_k8s,
                "kubernetes.client": mock_client,
                "kubernetes.config": mock_config,
            },
        ),
    ):
        mock_settings.kube_config = ""
        from mcp_hub.tools.k8s_tools import _get_k8s_client

        _get_k8s_client()
        mock_config.load_kube_config.assert_called_once()
