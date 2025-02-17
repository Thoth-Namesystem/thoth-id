from typing import Dict
from hathor.nanocontracts.blueprint import Blueprint
from hathor.nanocontracts.context import Context
from hathor.nanocontracts.exception import NCFail
from hathor.nanocontracts.types import Address, Amount, public, view

class NameRegistry:
    def __init__(self, owner_address: Address, resolving_address: Address):
        self.owner_address = owner_address
        self.resolving_address = resolving_address
        self.metadata = {}  # Dictionary to store personalized information

    def update_owner_address(self, new_owner_address: Address):
        """Update the resolving address."""
        self.owner_address = new_owner_address

    def update_resolving_address(self, new_resolving_address: Address):
        """Update the resolving address."""
        self.resolving_address = new_resolving_address

    def add_metadata(self, key, value):
        """Add personalized metadata, such as social media or contact info."""
        self.metadata[key] = value

    def get_metadata(self, key):
        """Retrieve metadata by key."""
        return self.metadata.get(key, "Not found")

    def remove_metadata(self, key):
        """Remove metadata by key."""
        if key in self.metadata:
            del self.metadata[key]

    def __str__(self):
        return str(dict(self))
    
    def __dict__(self):
        return {
            "owner_address": self.owner_address,
            "resolving_address": self.resolving_address,
            "metadata": self.metadata
        }



class ThothNamer(Blueprint):
    """A name service blueprint for registering and managing domain names."""
    
    # State variables
    domain: str  # Base domain (e.g., "htr")
    names: Dict[str, dict[str, Address]]  # Mapping of names to owner addresses
    dev_address: Address  # Developer address for receiving fees
    fee: Amount  # Fee for registering a name
    total_fee: Amount  # Total fees collected
    
    @public
    def initialize(self, ctx: Context, domain: str, fee: Amount) -> None:
        """Initialize the name service with a base domain and registration fee."""
        if not domain:
            raise NCFail("Domain cannot be empty")
        if fee <= 0:
            raise NCFail("Fee must be a postive number")
            
        self.domain = domain
        self.fee = fee
        self.total_fee = 0
        self.dev_address = ctx.address
    
    @public
    def create_name(self, ctx: Context, name: str) -> None:
        """Register a new name under the domain."""
        if not self.validate_name(name):
            raise NCFail("Invalid name format")
        if self.check_name_existence(name):
            raise NCFail("Name already registered")
            
        # Verify fee payment
        action = next(iter(ctx.actions.values()))
        if action.amount < self.fee:
            raise NCFail("Insufficient fee")
            
        self.names[name] = {
            "owner_address": ctx.address,
            "resolving_address": ctx.address
        }
        self.total_fee += self.fee
    
    @public
    def change_fee(self, ctx: Context, fee: Amount) -> None:
        """Change the registration fee."""
        if ctx.address != self.dev_address:
            raise NCFail("Only dev can change fee")
        if fee <= 0:
            raise NCFail("Fee must be a postive number")
            
        self.fee = fee
    
    @public
    def change_dev_address(self, ctx: Context, new_dev_address: Address) -> None:
        """Change the developer address."""
        if ctx.address != self.dev_address:
            raise NCFail("Only dev can change dev address")
            
        self.dev_address = new_dev_address
    
    @public
    def change_name_owner(self, ctx: Context, name: str, new_owner_address: Address) -> None:
        """Transfer ownership of a name to a new address."""
        if not self.check_name_existence(name):
            raise NCFail("Name not registered")
        if self.names[name].owner_address != ctx.address:
            raise NCFail("Only name owner can transfer")
            
        self.names[name]['owner_address'] = ctx.address
    
    @view
    def resolve_name(self, name: str) -> Address:
        """Get the address associated with a name."""
        if not self.check_name_existence(name):
            raise NCFail("Name not registered")
            
        return self.names[name]['resolving_address']
    
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