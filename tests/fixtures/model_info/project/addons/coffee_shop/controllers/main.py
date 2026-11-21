# Opens the orders action from a controller.
ORDERS_ACTION = 'coffee.action_coffee_order'


def retarget(env, view):
    view.inherit_id = env.ref('coffee.view_coffee_order_form')
