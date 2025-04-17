from typing import Any
import kubernetes
from kubernetes import client, config
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.routing import Mount, Route
from mcp.server import Server
import uvicorn
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server for K8s tools
mcp = FastMCP("k8s_pod_query")

# 尝试加载 Kubernetes 配置
try:
    config.load_kube_config(context='kind-mcp-server')
    logger.info("✅ 成功从默认位置加载Kubernetes配置")
except Exception as e:
    logger.warning(f"⚠️ 无法从默认位置加载Kubernetes配置: {e}")
    try:
        config.load_incluster_config()
        logger.info("✅ 成功从集群内部加载Kubernetes配置")
    except Exception as e:
        logger.error(f"❌ 无法加载Kubernetes配置: {e}")

# 创建 Kubernetes API 客户端
v1 = client.CoreV1Api()

@mcp.tool()
async def get_pods(namespace: str = None) -> str:
    """获取指定命名空间或所有命名空间的 Pod 信息

    Args:
        namespace: 可选的命名空间名称，如果为 None 则返回所有命名空间的 Pod
    """
    try:
        if namespace:
            pods = v1.list_namespaced_pod(namespace=namespace)
        else:
            pods = v1.list_pod_for_all_namespaces()

        if not pods.items:
            return "No pods found."

        pod_info = []
        for pod in pods.items:
            pod_details = f"""
Pod: {pod.metadata.name}
Namespace: {pod.metadata.namespace}
Status: {pod.status.phase}
Container Status: {pod.status.container_statuses[0].state}
IP: {pod.status.pod_ip}
Node: {pod.spec.node_name}
Created: {pod.metadata.creation_timestamp}
"""
            pod_info.append(pod_details)

        return "\n---\n".join(pod_info)
    except Exception as e:
        logger.error(f"获取 Pod 信息时出错: {e}")
        return f"Error retrieving pods: {str(e)}"

@mcp.tool()
async def get_pod_logs(pod_name: str, namespace: str = 'default', tail_lines: int = 50) -> str:
    """获取特定 Pod 的日志

    Args:
        pod_name: Pod 名称
        namespace: 命名空间，默认为 'default'
        tail_lines: 返回的日志行数，默认为 50
    """
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name, 
            namespace=namespace, 
            tail_lines=tail_lines
        )
        return logs
    except Exception as e:
        logger.error(f"获取 Pod 日志时出错: {e}")
        return f"Error retrieving pod logs: {str(e)}"

@mcp.tool()
async def create_pod(pod_name: str, namespace: str = 'default', image: str = 'nginx') -> str:
    """创建一个新的 Pod

    Args:
        pod_name: Pod 名称
        namespace: 命名空间，默认为 'default'
        image: 容器镜像，默认为 'nginx'
    """
    try:
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": pod_name, "namespace": namespace},
            "spec": {
                "containers": [{"name": pod_name, "image": image}]
            }
        }
        v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
        return f"Pod {pod_name} created in namespace {namespace}."
    except Exception as e:
        logger.error(f"创建 Pod 时出错: {e}")
        return f"Error creating pod: {str(e)}"
    
@mcp.tool()
async def create_namespace(namespace: str) -> str:
    """创建一个新的命名空间
    
    Args:
        namespace: 命名空间名称
    """
    try:
        namespace_manifest ={
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": { "name": namespace}
        }
        v1.create_namespace(body=namespace_manifest)
        return f"Namespace {namespace} created."
    except Exception as e:
        logger.error(f"创建命名空间时出错: {e}")
        return f"Error creating namespace: {str(e)}"

@mcp.tool()
async def delete_pod(pod_name: str, namespace: str = 'default') -> str:
    """删除指定的 Pod

    Args:
        pod_name: Pod 名称
        namespace: 命名空间，默认为 'default'
    """
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        return f"Pod {pod_name} deleted from namespace {namespace}."
    except Exception as e:
        logger.error(f"删除 Pod 时出错: {e}")
        return f"Error deleting pod: {str(e)}"

@mcp.tool()
async def delete_namespace(namespace: str) -> str:
    """删除指定的命名空间

    Args:
        namespace: 命名空间名称
    """
    try:
        v1.delete_namespace(name=namespace)
        return f"Namespace {namespace} deleted."
    except Exception as e:
        logger.error(f"删除命名空间时出错: {e}")
        return f"Error deleting namespace: {str(e)}"
@mcp.tool()
async def get_pod_events(pod_name: str, namespace: str = 'default') -> str:
    """获取指定 Pod 的事件

    Args:
        pod_name: Pod 名称
        namespace: 命名空间，默认为 'default'
    """
    try:
        events = v1.list_namespaced_event(namespace=namespace)
        pod_events = [event for event in events.items if event.involved_object.name == pod_name]

        if not pod_events:
            return "No events found for this pod."

        event_info = []
        for event in pod_events:
            event_details = f"""


Event: {event.message}
Reason: {event.reason}
Type: {event.type}
Source: {event.source.component}
First Seen: {event.first_timestamp}
Last Seen: {event.last_timestamp}
"""
            event_info.append(event_details)
        return "\n---\n".join(event_info)
    except Exception as e:
        logger.error(f"获取 Pod 事件时出错: {e}")
        return f"Error retrieving pod events: {str(e)}"
    
def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """创建 Starlette 应用程序，支持 SSE"""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        async with sse.connect_sse(
                request.scope,
                request.receive,
                request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

if __name__ == "__main__":
    mcp_server = mcp._mcp_server  # noqa: WPS437

    import argparse
    
    parser = argparse.ArgumentParser(description='Run K8s Pod Query MCP SSE-based server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8081, help='Port to listen on')
    args = parser.parse_args()

    # 创建 SSE 请求处理
    starlette_app = create_starlette_app(mcp_server, debug=True)

    uvicorn.run(starlette_app, host=args.host, port=args.port)