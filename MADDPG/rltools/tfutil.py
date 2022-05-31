import numpy as np
import tensorflow as tf

from rltools import util


def logsumexp(a, axis, name=None):
    """
    Like scipy.misc.logsumexp with keepdims=True
    (does NOT eliminate the singleton axis)
    """
    with tf.op_scope([a, axis], name, 'logsumexp') as scope:
        a = tf.convert_to_tensor(a, name='a')
        axis = tf.convert_to_tensor(axis, name='axis')

        amax = tf.reduce_max(a, axis, keep_dims=True)
        shifted_result = tf.log(tf.reduce_sum(tf.exp(a - amax), axis, keep_dims=True))
        return tf.add(shifted_result, amax, name=scope)


def lookup_last_idx(a, inds, name=None):
    """
    Looks up indices in a. e.g. a[[1, 2, 3]] = [a[1], a[2], a[3]]
    a is a d1 x d2 ... dn tensor
    inds is a d1 x d2 ... d(n-1) tensor of integers
    returns the tensor
    out[i_1,...,i_{n-1}] = a[i_1,...,i_{n-1}, inds[i_1,...,i_{n-1}]]
    """
    with tf.op_scope([a, inds], name, 'lookup_last_idx') as scope:
        a = tf.convert_to_tensor(a, name='a')
        inds = tf.convert_to_tensor(inds, name='inds')

        # Flatten the arrays
        ashape, indsshape = tf.shape(a), tf.shape(inds)
        aflat, indsflat = tf.reshape(a, [-1]), tf.reshape(inds, [-1])

        # Compute the indices corresponding to inds in the flattened array
        # TODO Causes UserWarning: Converting sparse IndexedSlices to a dense Tensor of unknown shape.
        delta = tf.gather(ashape, tf.size(ashape) - 1)  # i.e. delta = ashape[-1],
        aflatinds = tf.range(0, limit=tf.size(a), delta=delta) + indsflat

        # Look up the desired elements in the flattened array, and reshape
        # to the original shape
        return tf.reshape(tf.gather(aflat, aflatinds), indsshape, name=scope)


def flatcat(arrays, name=None):
    """
    Flattens arrays and concatenates them in order.
    """
    with tf.op_scope(arrays, name, 'flatcat') as scope:
        return tf.concat(0, [tf.reshape(a, [-1]) for a in arrays], name=scope)


def fixedgradients(loss, params):
    """
    Replace None by zero shaped as params
    """
    grads = tf.gradients(loss, xs=params)
    for idx, (grad, param) in enumerate(zip(grads, params)):
        if grad is None:
            grads[idx] = tf.zeros_like(param)

    return grads


def unflatten_into_tensors(flatparams_P, output_shapes, name=None):
    """
    Unflattens a vector produced by flatcat into a list of tensors of the specified shapes.
    """
    with tf.op_scope([flatparams_P], name, 'unflatten_into_tensors') as scope:
        outputs = []
        curr_pos = 0
        for shape in output_shapes:
            size = np.prod(shape).astype('int')
            flatval = flatparams_P[curr_pos:curr_pos + size]
            outputs.append(tf.reshape(flatval, shape))
            curr_pos += size
        assert curr_pos == flatparams_P.get_shape().num_elements(), "{} != {}".format(
            curr_pos, flatparams_P.get_shape().num_elements())
        return tf.tuple(outputs, name=scope)


def unflatten_into_vars(flatparams_P, param_vars, name=None):
    """
    Unflattens a vector produced by flatcat into the original variables
    """
    with tf.op_scope([flatparams_P] + param_vars, name, 'unflatten_into_vars') as scope:
        tensors = unflatten_into_tensors(flatparams_P,
                                         [v.get_shape().as_list() for v in param_vars])
        return tf.group(*[v.assign(t) for v, t in util.safezip(param_vars, tensors)], name=scope)


def subsample_feed(feed, frac):
    assert isinstance(feed, tuple) and len(feed) >= 1
    assert isinstance(frac, float) and 0. < frac <= 1.
    l = feed[0].shape[0]
    assert all(a.shape[0] == l for a in feed), 'All feed entries must have the same length'
    subsamp_inds = np.random.choice(l, size=int(frac * l))
    return tuple(a[subsamp_inds, ...] for a in feed)


def function(inputs, outputs, updates=None):
    if isinstance(outputs, list):
        return TFFunction(inputs, outputs, updates)
    elif isinstance(outputs, dict):
        f = TFFunction(inputs, outputs.values(), updates)
        return lambda *inputs, **kwargs: dict(zip(outputs.keys(), f(*inputs, **kwargs)))
    else:
        f = TFFunction(inputs, [outputs], updates)
        return lambda *inputs, **kwargs: f(*inputs, **kwargs)[0]


class TFFunction(object):

    def __init__(self, inputs, outputs, updates):
        self._inputs = inputs
        self._outputs = outputs
        self._updates = [] if updates is None else updates

    def __call__(self, *inputs_, **kwargs):
        assert len(inputs_) == len(self._inputs)
        feed_dict = dict(zip(self._inputs, inputs_))
        sess = kwargs.pop('sess', tf.get_default_session())
        results = sess.run(self._outputs + self._updates, feed_dict=feed_dict)
        if any(result is not None and np.isnan(result).any() for result in results):
            raise RuntimeError("NaN encountered")

        return results[:len(self._outputs)]
