"""统一分页构造器：响应 {list, total, page, page_size}。"""
from math import ceil


def paginate(query, page: int = 1, page_size: int = 10, order_by=None):
    """对 SQLAlchemy 查询对象分页；order_by 可选传排序表达式。"""
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    total = query.count()
    q = query
    if order_by is not None:
        q = q.order_by(order_by)
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size) if total else 0,
    }
