type QueryStateProps = {
  label: string;
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  error?: unknown;
};

function errorText(error: unknown): string | null {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  return null;
}

export function QueryState({ label, isLoading = false, isError = false, isEmpty = false, error }: QueryStateProps) {
  if (isLoading) {
    return (
      <div role="status" className="rounded-md border border-hairline-ondark bg-surface-card-dark px-md py-sm text-body-sm text-muted">
        {label}加载中
      </div>
    );
  }

  if (isError) {
    const detail = errorText(error);
    return (
      <div role="alert" className="rounded-md border border-trading-down bg-surface-card-dark px-md py-sm text-body-sm text-trading-down">
        {label}加载失败{detail ? `：${detail}` : ""}
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div role="status" className="rounded-md border border-hairline-ondark bg-surface-card-dark px-md py-sm text-body-sm text-muted">
        暂无{label}数据
      </div>
    );
  }

  return null;
}
