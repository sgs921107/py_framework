#!/usr/bin/env python
# -*- coding=utf8 -*-
from typing import List, Union
from dataclasses import dataclass

from aredis import StrictRedis, StrictRedisCluster

from common import config
from common.conts import DEFAULT_REDIS_EXPIRES, \
    DEFAULT_REDIS_PARAMS, DEFAULT_REDIS_QUEUE_SIZE


class ScriptsCommandMixin:

    hsetex_script = """
    local name = KEYS[1]
    local expire_time = ARGV[1]
    local key = ARGV[2]
    local value = ARGV[3]
    local ret = redis.call("hset", name, key, value)
    redis.call("expire", name, expire_time)
    return ret
    """

    hmsetex_script = """
    local name = KEYS[1]
    local expire_time = ARGV[1]
    local ret = redis.call("hmset", name, unpack(ARGV, 2))
    redis.call("expire", name, expire_time)
    return ret
    """

    saddex_script = """
    local name = KEYS[1]
    local expire_time = ARGV[1]
    local ret = redis.call("sadd", name, unpack(ARGV, 2))
    redis.call("expire", name, expire_time)
    return ret
    """

    spoprem_script = """
    local name = KEYS[1]
    local num = ARGV[1]
    local ret = redis.call("srandmember", name, num)
    if next(ret) ~= nil
    then
        redis.call("srem", name, unpack(ret))
    end
    return ret
    """

    # 向zset中加入元素并只保留指定数量的元素
    zaddrembyrank_script = """
    local name = KEYS[1]
    local startNum = ARGV[1]
    local stopNum = ARGV[2]
    local ret = redis.call("zadd", name, unpack(ARGV, 3))
    redis.call("zremrangebyrank", name, startNum, stopNum)
    return ret
    """

    # 向list中插入元素并只保留指定数量的元素
    lpushtrim_script = """
    local name = KEYS[1]
    local startNum = ARGV[1]
    local stopNum = ARGV[2]
    local ret = redis.call("lpush", name, unpack(ARGV, 3))
    if( ret > stopNum + 1 )
    then
        redis.call("ltrim", name, startNum, stopNum)
    end
    return ret
    """

    # 从list左端插入数据并设置过期时间
    lpushex_script = """
    local name = KEYS[1]
    local expire_time = ARGV[1]
    local unpack = unpack or table.unpack
    local ret = redis.call("lpush", name, unpack(ARGV, 2))
    redis.call("expire", name, expire_time)
    return ret
    """

    # 从list右端插入数据并设置过期时间
    rpushex_script = """
    local name = KEYS[1]
    local expire_time = ARGV[1]
    local unpack = unpack or table.unpack
    local ret = redis.call("rpush", name, unpack(ARGV, 2))
    redis.call("expire", name, expire_time)
    return ret
    """

    async def hsetex(self, name, key, value, ex=DEFAULT_REDIS_EXPIRES):
        return await self.eval(self.hsetex_script, 1, name, ex, key, value)

    async def hmsetex(self, name, data, ex=DEFAULT_REDIS_EXPIRES):
        kvs = list()
        for key, val in data.items():
            # 过滤None值
            if val is None:
                continue
            kvs.extend([key, val])
        return await self.eval(self.hmsetex_script, 1, name, ex, *kvs)

    async def setex(self, name, value, time=DEFAULT_REDIS_EXPIRES):
        """
        重写setex  给定默认时间
        """
        return await super().setex(name, time, value)

    async def saddex(self, name, *values, ex=DEFAULT_REDIS_EXPIRES):
        """
        向集合中追加元素，并设置过期时间
        """
        return await self.eval(self.saddex_script, 1, name, ex, *values)

    async def lpushtrim(self, name, *values, length=DEFAULT_REDIS_QUEUE_SIZE) -> int:
        """
        向list中插入元素并只保留指定数量的元素
        """
        return await self.eval(
            self.lpushtrim_script, 1, name, 0, length - 1, *values
        )

    async def zaddrembyrank(self, name, mapping, length=DEFAULT_REDIS_QUEUE_SIZE):
        """
        向zset中加入元素并只保留指定数量的元素
        """
        list_mapping = list()
        for k, v in mapping.items():
            list_mapping.extend([v, k])
        return await self.eval(
            self.zaddrembyrank_script, 1, name, 0, -(length + 1), *list_mapping
        )

    async def spoprem(self, name, num: int = 1) -> List:
        """
        随机移除并返回若干个元素
        """
        return await self.eval(self.spoprem_script, 1, name, num)

    async def lpushex(self, name, *values, ex=DEFAULT_REDIS_EXPIRES):
        return await self.eval(self.lpushex_script, 1, name, ex, *values)

    async def rpushex(self, name, *values, ex=DEFAULT_REDIS_EXPIRES):
        return await self.eval(self.rpushex_script, 1, name, ex, *values)


class PubSubCommandExtension:

    @dataclass
    class MessageType:
        message: str = "message"
        subscribe: str = "subscribe"

    async def subscribe(self, *args, ignore_subscribe_messages=False, **kwargs):
        """
        订阅一个/多个频道
        :param ignore_subscribe_messages: 是否忽略订阅信息，实例化Pubsub时的可选参数
        :param args: 要订阅频道
        :param kwargs: 要订阅的频道
        :return:
        """
        pubsub = self.pubsub(ignore_subscribe_messages=ignore_subscribe_messages)
        await pubsub.subscribe(*args, **kwargs)
        return pubsub


mixins = [ScriptsCommandMixin, PubSubCommandExtension]


class _ARedis(StrictRedis, *mixins):
    pass


class _ARedisCluster(StrictRedisCluster, *mixins):
    pass


class ARedis(object):
    instance = None

    @classmethod
    def get_instance(cls) -> Union[_ARedis, _ARedisCluster]:
        if cls.instance is None:
            params = DEFAULT_REDIS_PARAMS.copy()
            params["host"] = config.get("redis_host")
            params["port"] = config.get("redis_port")
            params["password"] = config.get("redis_password")
            cluster = config.get("redis_mode") == "cluster"
            if cluster:
                redis_cls = _ARedisCluster
                params["skip_full_coverage_check"] = True
            else:
                redis_cls = _ARedis
                params["db"] = config.get("redis_db")
            cls.instance = redis_cls(**params)
        return cls.instance
