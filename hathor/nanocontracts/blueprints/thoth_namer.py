from typing import Dict
from hathor.crypto.util import get_address_b58_from_bytes
from hathor.nanocontracts.blueprint import Blueprint
from hathor.nanocontracts.context import Context
from hathor.nanocontracts.exception import NCFail
from hathor.nanocontracts.types import Address, Amount, NCAction, NCActionType, public, view

# class NameRegistry:
#     def __init__(self, owner_address: Address, resolving_address: Address):
#         self.owner_address = owner_address
#         self.resolving_address = resolving_address
#         self.metadata = {}  # Dictionary to store personalized information

#     def update_owner_address(self, new_owner_address: Address):
#         """Update the resolving address."""
#         self.owner_address = new_owner_address

#     def update_resolving_address(self, new_resolving_address: Address):
#         """Update the resolving address."""
#         self.resolving_address = new_resolving_address

#     def add_metadata(self, key, value):
#         """Add personalized metadata, such as social media or contact info."""
#         self.metadata[key] = value

#     def get_metadata(self, key):
#         """Retrieve metadata by key."""
#         return self.metadata.get(key, "Not found")

#     def remove_metadata(self, key):
#         """Remove metadata by key."""
#         if key in self.metadata:
#             del self.metadata[key]

#     def __str__(self):
#         return str(dict(self))
    
#     def __dict__(self):
#         return {
#             "owner_address": self.owner_address,
#             "resolving_address": self.resolving_address,
#             "metadata": self.metadata
#         }

class NameNotFound(NCFail):
    pass

class NameAlreadyExists(NCFail):
    pass

class NotAuthorized(NCFail):
    pass

class InvalidNameFormat(NCFail):
    pass

class WithdrawalNotAllowed(NCFail):
    pass

class DepositNotAllowed(NCFail):
    pass

class InsufficientBalance(NCFail):
    pass

class InvalidFee(NCFail):
    pass

class InvalidDomain(NCFail):
    pass

class TooManyActions(NCFail):
    pass

class InvalidToken(NCFail):
    pass

class ThothNamer(Blueprint):
    """A name service blueprint for registering and managing domain names."""
    
    # State variables
    domain: str  # Base domain (e.g., "htr")
    names: Dict[str, dict[str, Address]] # Mapping of names to owner addresses TODO: fix changing address and rollback to Dict[str, dict[str, str]]
    dev_address: Address  # Developer address for receiving fees
    fee: Amount  # Fee for registering a name
    total_fee: Amount  # Total fees collected
    
    @public
    def initialize(self, ctx: Context, domain: str, fee: Amount) -> None:
        """Initialize the name service with a base domain and registration fee."""
        if not domain:
            raise InvalidDomain("Domain cannot be empty.")
        if fee <= 0:
            raise InvalidFee("Fee must be a positive value.")
            
        self.domain = domain
        self.fee = fee
        self.total_fee = 0
        self.dev_address = ctx.address
    
    @public
    def create_name(self, ctx: Context, name: str) -> None:
        """Register a new name under the domain."""
        if not self.validate_name(name):
            raise InvalidNameFormat
        if self.check_name_existence(name):
            raise NameAlreadyExists
            
        # Verify fee payment
        #action = next(iter(ctx.actions.values()))
        action = self._get_action(ctx)
        if action.amount < self.fee:
            raise InsufficientBalance("Deposit amount is less than fee.")
            
        self.names[name] = {
            "owner_address": ctx.address,
            "resolving_address": ctx.address
        }
        self.total_fee += self.fee
    
    @public
    def change_fee(self, ctx: Context, fee: Amount) -> None:
        """Change the registration fee."""
        if ctx.address != self.dev_address:
            raise NotAuthorized("Only dev can change fee.")
        if fee <= 0:
            raise InvalidFee("Fee must be a positive value.")
            
        self.fee = fee
    
    @public
    def change_dev_address(self, ctx: Context, new_dev_address: Address) -> None:
        """Change the developer address."""
        if ctx.address != self.dev_address:
            raise NotAuthorized
            
        self.dev_address = new_dev_address
    
    @public
    def change_name_owner(self, ctx: Context, name: str, new_owner_address: Address) -> None:
        """Transfer ownership of a name to a new address."""
        if not self.check_name_existence(name):
            raise NameNotFound
        if self.names[name]['owner_address'] != ctx.address:
            raise NotAuthorized
        
        self.names[name] = self._update_owner_address(name, new_owner_address)

    @public
    def change_resolving_address(self, ctx: Context, name: str, new_resolving_address: Address) -> None:
        """Change the resolvign address of a name when authorized."""
        if not self.check_name_existence(name):
            raise NameNotFound
        if self.names[name]["owner_address"] != ctx.address:
            raise NotAuthorized
        
        self.names[name] = self._update_resolving_address(name, new_resolving_address)
    
    @view
    def resolve_name(self, name: str) -> str:
        """Get the address associated with a name."""
        if not self.check_name_existence(name):
            raise NameNotFound
            
        return get_address_b58_from_bytes(self.names[name]['resolving_address'])
    
    @view
    def validate_name(self, name: str) -> bool:
        """Verify if the name exists and is valid."""
        # Check if name is empty
        if not name:
            return False
            
        # Check length (e.g., between 3 and 32 characters)
        if len(name) < 3 or len(name) > 32:
            return False
            
        # Only allow lowercase letters, numbers, and hyphens
        allowed_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-")
        if not all(c in allowed_chars for c in name):
            return False
            
        # Don't allow names starting or ending with hyphen
        if name[0] == '-' or name[-1] == '-':
            return False
            
        return True
    
    @view
    def check_name_existence(self, name: str) -> bool:
        return name in self.names
    
    @view
    def get_name_owner(self, name: str) -> Address:
        """Get the name owner's address."""
        if name not in self.names:
            raise NameNotFound
        
        return self.names[name]['owner_address']
    
    @view
    def get_dev_address(self) -> Address:
        """Get the developer's address."""
        return get_address_b58_from_bytes(self.dev_address)
    
    def _get_action(self, ctx: Context) -> NCAction:
        """Return the only action available; fails otherwise."""
        if len(ctx.actions) != 1:
            raise TooManyActions('Only one action supported.')
        action = next(iter(ctx.actions.values()))
        if ctx.address != self.dev_address and action.type == NCActionType.WITHDRAWAL:
            raise WithdrawalNotAllowed('Only dev can withdraw.')
        if action.token_uid == b'00':
            raise InvalidToken(f'Token different from HTR.')
        return action
    
    def _update_resolving_address(self, name, new_resolving_address):
        """Get and update a resoling address. Returns a new dict with updated values."""
        temp = self.names[name]
        temp.update({
            'resolving_address': new_resolving_address
        })

        return temp
    
    def _update_owner_address(self, name, new_owner_address):
        """Get and update a owner address. Returns a new dict with updated values."""
        temp = self.names[name]
        temp.update({
            'owner_address': new_owner_address
        })

        return temp