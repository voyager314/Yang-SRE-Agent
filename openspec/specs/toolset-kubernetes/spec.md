## Purpose

Kubernetes 工具集，封装 kubectl 命令为 LLM 可调用的工具，支持 Pod、Service、Event 等资源查询和日志获取。

## ADDED Requirements

### Requirement: kubectl resource query
系统 SHALL 提供 kubectl 资源查询工具，支持获取 Pod、Service、Deployment、Event 等 Kubernetes 资源信息。

#### Scenario: 获取命名空间下的 Pod 列表
- **WHEN** LLM 调用 kubernetes_get_resources(kind="pods", namespace="production")
- **THEN** 系统执行 `kubectl get pods -n production -o json` 并返回结果

#### Scenario: 获取所有命名空间的事件
- **WHEN** LLM 调用 kubernetes_get_events(namespace="all")
- **THEN** 系统执行 `kubectl get events --all-namespaces --sort-by='.lastTimestamp'` 并返回结果

### Requirement: kubectl describe
系统 SHALL 提供资源详情查询工具。

#### Scenario: 描述指定 Pod
- **WHEN** LLM 调用 kubernetes_describe(kind="pod", name="checkout-abc", namespace="production")
- **THEN** 系统执行 `kubectl describe pod checkout-abc -n production` 并返回结果

### Requirement: kubectl logs
系统 SHALL 提供 Pod 日志获取工具，支持 tail 行数限制和容器选择。

#### Scenario: 获取 Pod 最近日志
- **WHEN** LLM 调用 kubernetes_logs(pod="checkout-abc", namespace="production", tail=200)
- **THEN** 系统执行 `kubectl logs checkout-abc -n production --tail=200` 并返回结果

#### Scenario: 获取前一个容器日志
- **WHEN** LLM 调用 kubernetes_logs(pod="checkout-abc", namespace="production", previous=true)
- **THEN** 系统执行 `kubectl logs checkout-abc -n production --previous` 并返回结果

### Requirement: kubectl prerequisite
Kubernetes 工具集 SHALL 要求本地 kubectl 可执行且 kubeconfig 有效。

#### Scenario: kubectl 未安装
- **WHEN** 系统检查先决条件时 `kubectl version --client` 执行失败
- **THEN** Kubernetes 工具集标记为不可用，给出提示"kubectl not found"
