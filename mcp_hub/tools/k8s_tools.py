"""Kubernetes cluster tools for MCP."""

from __future__ import annotations

import asyncio
import functools
from typing import Any

from mcp_hub.config import settings


def _get_k8s_client() -> Any:
    """Get a configured Kubernetes API client."""
    from kubernetes import client, config

    if settings.kube_config:
        config.load_kube_config(config_file=settings.kube_config)
    else:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
    return client


def _run_sync(func, *args, **kwargs):
    """Run a synchronous kubernetes-client call in a thread."""
    return asyncio.to_thread(functools.partial(func, *args, **kwargs))


async def get_cluster_status() -> str:
    """Get overall Kubernetes cluster status including node health and resource usage."""
    k8s = _get_k8s_client()
    v1 = k8s.CoreV1Api()

    nodes = await _run_sync(v1.list_node)
    lines = ["## Cluster Nodes\n"]
    for node in nodes.items:
        name = node.metadata.name
        conditions = {c.type: c.status for c in node.status.conditions}
        ready = conditions.get("Ready", "Unknown")
        roles = [
            l.replace("node-role.kubernetes.io/", "")
            for l in (node.metadata.labels or {})
            if l.startswith("node-role.kubernetes.io/")
        ]
        cap = node.status.capacity
        lines.append(
            f"- **{name}** | Ready: {ready} | Roles: {', '.join(roles) or 'worker'} "
            f"| CPU: {cap.get('cpu', '?')} | Memory: {cap.get('memory', '?')}"
        )
    return "\n".join(lines)


async def list_namespaces() -> str:
    """List all Kubernetes namespaces and their status."""
    k8s = _get_k8s_client()
    v1 = k8s.CoreV1Api()

    namespaces = await _run_sync(v1.list_namespace)
    lines = ["## Namespaces\n"]
    for ns in namespaces.items:
        age = ns.metadata.creation_timestamp.strftime("%Y-%m-%d")
        lines.append(f"- **{ns.metadata.name}** | {ns.status.phase} | created: {age}")
    return "\n".join(lines)


async def get_namespace_pods(namespace: str = "default") -> str:
    """List pods in a namespace with their status.

    Args:
        namespace: Kubernetes namespace (default: "default")
    """
    k8s = _get_k8s_client()
    v1 = k8s.CoreV1Api()

    pods = await _run_sync(v1.list_namespaced_pod, namespace=namespace)
    lines = [f"## Pods in {namespace}\n"]
    for pod in pods.items:
        phase = pod.status.phase
        restarts = sum(
            (cs.restart_count for cs in (pod.status.container_statuses or []))
        )
        lines.append(f"- **{pod.metadata.name}** | {phase} | restarts: {restarts}")
    return "\n".join(lines) if len(lines) > 1 else f"No pods found in namespace {namespace}."


async def get_services(namespace: str = "") -> str:
    """List Kubernetes services, optionally filtered by namespace.

    Args:
        namespace: Optional namespace filter. Empty string for all namespaces.
    """
    k8s = _get_k8s_client()
    v1 = k8s.CoreV1Api()

    if namespace:
        services = await _run_sync(v1.list_namespaced_service, namespace=namespace)
    else:
        services = await _run_sync(v1.list_service_for_all_namespaces)

    lines = ["## Services\n"]
    for svc in services.items:
        svc_type = svc.spec.type
        ports = ", ".join(
            f"{p.port}/{p.protocol}" for p in (svc.spec.ports or [])
        )
        external = ""
        if svc.status.load_balancer and svc.status.load_balancer.ingress:
            ips = [i.ip for i in svc.status.load_balancer.ingress if i.ip]
            if ips:
                external = f" | external: {', '.join(ips)}"
        lines.append(
            f"- **{svc.metadata.namespace}/{svc.metadata.name}** | {svc_type} "
            f"| ports: {ports}{external}"
        )
    return "\n".join(lines)


async def get_deployments(namespace: str = "") -> str:
    """List deployments with replica status.

    Args:
        namespace: Optional namespace filter. Empty string for all namespaces.
    """
    k8s = _get_k8s_client()
    apps = k8s.AppsV1Api()

    if namespace:
        deps = await _run_sync(apps.list_namespaced_deployment, namespace=namespace)
    else:
        deps = await _run_sync(apps.list_deployment_for_all_namespaces)

    lines = ["## Deployments\n"]
    for d in deps.items:
        ready = d.status.ready_replicas or 0
        desired = d.spec.replicas or 0
        lines.append(
            f"- **{d.metadata.namespace}/{d.metadata.name}** | {ready}/{desired} ready"
        )
    return "\n".join(lines)
