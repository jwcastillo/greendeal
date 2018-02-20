from boa.blockchain.vm.Neo.Action import RegisterAction
from boa.blockchain.vm.Neo.Blockchain import GetHeight, GetHeader
from boa.blockchain.vm.Neo.Runtime import Log, GetTrigger, CheckWitness
from boa.blockchain.vm.Neo.Storage import Get, GetContext, Put, Delete
from boa.blockchain.vm.Neo.TriggerType import Application, Verification
from boa.code.builtins import concat

from utils.txio import get_asset_attachments
from utils.promo import get_promo_storage_keys


OWNER = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

OnTransfer = RegisterAction('transfer', 'addr_from', 'addr_to', 'amount')


def Main(operation, args):
    trigger = GetTrigger()

    if trigger == Verification():
        is_owner = CheckWitness(OWNER)
        if is_owner:
            return True
        return False

    elif trigger == Application():
        # seller action
        if operation == 'create':
            if len(args) == 8:
                creator = args[0]  # public key
                promo_id = args[1]
                title = args[2]
                description = args[3]
                price_per_person = args[4]  # price in GAS
                expiration = args[5]
                min_count = args[6]
                max_count = args[7]

                success = CreatePromo(creator, promo_id, title, description, price_per_person, expiration, min_count, max_count)

                if success:
                    Log('Promo successfully created')
                    return True
                else:
                    Log('Error in creating promo')
                    return False
            else:
                Log('incorrect number of arguments')
                return False

        # seller action
        elif operation == 'delete':
            if len(args) == 1:
                promo_id = args[0]

                authorize = IsPromoCreator(promo_id)
                if authorize:
                    DeletePromo(promo_id)
                    Log('Promo successfully deleted')
                    return True
                else:
                    Log('Permission denied')
                    return False
            else:
                Log('incorrect number of arguments')
                return False

        # seller action
        elif operation == 'claim':
            if len(args) == 1:
                promo_id = args[0]

                authorize = IsPromoCreator(promo_id)
                if authorize:
                    success = ClaimFunds(promo_id)
                    if success:
                        Log('Promo funds successfully claimed')
                    else:
                        Log('Error in claiming funds')
                        return True
                else:
                    Log('Permission denied')
                    return False
            else:
                Log('incorrect number of arguments')
                return False

        # buyer action
        elif operation == 'buy':
            if len(args) == 3:
                buyer = args[0]
                promo_id = args[1]
                quantity = args[2]

                success = BuyPromo(buyer, promo_id, quantity)

                if success:
                    Log('Promo successfully purchased')
                    return True
                else:
                    Log('Error in purchasing promo')
                    return False
            else:
                Log('incorrect number of arguments')
                return False

        # buyer action
        elif operation == 'refund':
            if len(args) == 2:
                buyer = args[0]
                promo_id = args[1]

                authorize = CheckWitness(buyer)
                if authorize:
                    success = RefundPromo(buyer, promo_id)

                    if success:
                        Log('Refund successful')
                        return True
                    else:
                        Log('Error in refund')
                        return False
                else:
                    Log('Permission denied')
                    return False
            else:
                Log('incorrect number of arguments')
                return False

        # buyer/seller action
        elif operation == 'details':
            if len(args) == 1:
                promo_id = args[0]
                Details(promo_id)
                return True
            else:
                Log('incorrect number of arguments')
                return False

        else:
            Log('operation not found')
            return False

    return False

def CreatePromo(creator, promo_id, title, description, price_per_person, expiration, min_count, max_count):
    """
    Create a promo and "register" the details onto the blockchain/storage.

    Args:
        creator (str): public key
        promo_id (str):
        title (str): can not contain spaces
        description (str): can not contain spaces
        price_per_person (int): floats not supported in VM, price in GAS
        expiration (int): use unix GMT time
        min_count (int):
        max_count (int):

    Returns:
        (bool): True if promo created successfully
    """
    if price_per_person < 0:
        Log('price_per_person must be positive')
        return False

    if min_count <= 0:
        Log('min_count must be greater than zero')
        return False

    if min_count > max_count:
        Log('min_count must be less than or equal to max_count')
        return False

    height = GetHeight()
    current_block = GetHeader(height)
    current_time = current_block.Timestamp

    if current_time > expiration:
        Log('expiration must be greater than current time. '
            'Note: use unix GMT time')
        return False

    promo_exists = IsPromoExist(promo_id)
    if promo_exists:
        Log('promo_id is already taken')
        return False

    promo = get_promo_storage_keys(promo_id)

    context = GetContext()
    Put(context, promo_id, True)  # promo_exists
    Put(context, promo.creator_key, creator)
    Put(context, promo.title_key, title)
    Put(context, promo.description_key, description)
    Put(context, promo.price_per_person_key, price_per_person)
    Put(context, promo.expiration_key, expiration)
    Put(context, promo.min_count_key, min_count)
    Put(context, promo.max_count_key, max_count)
    Put(context, promo.purchased_count_key, 0)

    return True


def BuyPromo(buyer, promo_id, quantity):
    """
    Purchase <quantity> tickets for promo. Buyer public key + quantity bought
    is also stored in case of refund.

    Args:
        buyer (str): buyer's public key
        promo_id (str):
        quantity (int):

    Returns:
        (bool): True if promo purchased successfully
    """

    ### Series of checks to see if args are valid

    promo_exists = IsPromoExist(promo_id)
    if not promo_exists:
        Log('Promo not found')
        return False

    promo = get_promo_storage_keys(promo_id)

    context = GetContext()
    purchased_count = Get(context, promo.purchased_count_key)
    max_count = Get(context, promo.max_count_key)

    remaining = max_count - purchased_count

    if remaining == 0:
        Log('Promo has sold out!')
        return False

    if quantity < 1:
        Log('Please enter quantity of at least one')
        return False

    if remaining - quantity < 0:
        Log('Not enough tickets remaining, available amount: ')
        Log(remaining)
        return False

    expired = IsPromoExpired(promo_id)
    if expired:
        Log('Promo has expired!')
        return False

    buyer_key = concat(promo_id, buyer)
    purchased_quantity = Get(context, buyer_key)
    if purchased_quantity:
        Log('Promo already claimed using given public key')
        return False

    price_per_person = Get(context, promo.price_per_person_key)
    attachment = get_asset_attachments()
    # 10**8 multiplier to bring to NEO VM standards
    if attachment.gas_attached < (quantity * price_per_person) * 10**8:
        Log('Insufficient funds')
        return False

    ### Place purchase logic

    OnTransfer(attachment.sender_addr, attachment.receiver_addr, attachment.gas_attached)

    purchased_count += quantity
    Put(context, promo.purchased_count_key, purchased_count)

    # store quantity of tickets buyer purchased
    buyer_key = concat(promo_id, buyer)
    Put(context, buyer_key, quantity)

    return True


def DeletePromo(promo_id):
    expired = IsPromoExpired(promo_id)
    if expired:
        Log('Promo has already finished, can no longer delete it!')
        return False

    context = GetContext()
    Delete(context, promo_id)  # delete promo_exists

    return True


def ClaimFunds(promo_id):
    promo_exists = IsPromoExist(promo_id)
    if not promo_exists:
        Log('Promo not found')
        return False

    expired = IsPromoExpired(promo_id)
    if not expired:
        Log('Promo not over yet! Cannot claim funds yet')
        return False

    promo = get_promo_storage_keys(promo_id)

    context = GetContext()
    min_count = Get(context, promo.min_count_key)
    purchased_count = Get(context, promo.purchased_count_key)

    if purchased_count < min_count:
        Log('Not enough tickets were sold by deadline, buyers can claim refund')
        return False

    price_per_person = Get(context, promo.price_per_person_key)

    attachment = get_asset_attachments()
    funds_amount = purchased_count * price_per_person
    OnTransfer(attachment.receiver_addr, attachment.sender_addr, funds_amount)

    return True


def RefundPromo(buyer, promo_id):
    """
    Refund all of buyer's purchased tickets for specified promo

    Args:
        buyer (str): buyer's public key
        promo_id (str):

    Returns:
        (bool): True if successfully refunded
    """
    promo_exists = IsPromoExist(promo_id)
    if not promo_exists:
        Log('Promo not found')
        return False

    promo = get_promo_storage_keys(promo_id)

    expired = IsPromoExpired(promo_id)
    context = GetContext()
    min_count = Get(context, promo.min_count_key)
    purchased_count = Get(context, promo.purchased_count_key)

    # Cannot issue refund if minimum number of buyers has been met past deadline
    if expired and purchased_count > min_count:
        Log('Promo refund deadline has passed')
        return False

    buyer_key = concat(promo_id, buyer)
    refund_quantity = Get(context, buyer_key)
    if not refund_quantity:
        Log('No purchases were made using given public key')
        return False

    Delete(context, buyer_key)

    price_per_person = Get(context, promo.price_per_person_key)

    refund_amount = refund_quantity * price_per_person
    attachment = get_asset_attachments()
    OnTransfer(attachment.receiver_addr, attachment.sender_addr, refund_amount)

    # update purchased_count
    purchased_count -= refund_quantity
    Put(context, promo.purchased_count_key, purchased_count)

    return True


def Details(promo_id):
    """
    Prints details of specified promo:
    Creator, Title, Description, Price/person, Expiration Date, Min count,
    Max count, Purchased count

    Args:
        promo_id (str):

    Returns:
        (bool): True if promo found and details successfully printed
    """
    promo_exists = IsPromoExist(promo_id)
    if not promo_exists:
        Log('Promo not found')
        return False

    promo = get_promo_storage_keys(promo_id)

    context = GetContext()
    creator = Get(context, promo.creator_key)
    title = Get(context, promo.title_key)
    description = Get(context, promo.description_key)
    price_per_person = Get(context, promo.price_per_person_key)
    expiration = Get(context, promo.expiration_key)
    min_count = Get(context, promo.min_count_key)
    max_count = Get(context, promo.max_count_key)
    purchased_count = Get(context, promo.purchased_count_key)

    Log('Creator, Title, Description, Price/person, Expiration Date, '
        'Minimum count, Maximum count, Purchased count')
    Log(creator)
    Log(title)
    Log(description)
    Log(price_per_person)
    Log(expiration)
    Log(min_count)
    Log(max_count)
    Log(purchased_count)

    return True


def IsPromoCreator(promo_id):
    """
    Check if smart contract invoker is creator of promo

    Args:
        promo_id (str):

    Returns:
        (bool): True if contract invoker is creator of promo
    """
    promo_exists = IsPromoExist(promo_id)
    if not promo_exists:
        Log('Promo not found')
        return False

    context = GetContext()
    creator_key = concat(promo_id, 'creator')
    creator = Get(context, creator_key)

    return CheckWitness(creator)


def IsPromoExpired(promo_id):
    """
    Check if promo has expired or not

    Args:
        promo_id (str):

    Returns:
        (bool): True if promotion has expired
    """
    context = GetContext()
    expiration_key = concat(promo_id, 'expiration')
    expiration = Get(context, expiration_key)

    height = GetHeight()
    current_block = GetHeader(height)
    current_time = current_block.Timestamp

    expired = current_time > expiration
    return expired


def IsPromoExist(promo_id):
    """
    Check if promo is in Storage

    Args:
        promo_id (str):

    Returns:
        (bool): True if promo_id already exists in storage
    """
    context = GetContext()
    promo_exists = Get(context, promo_id)
    return promo_exists
