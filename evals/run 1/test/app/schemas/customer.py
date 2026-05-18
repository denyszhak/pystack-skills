from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.customer import Customer


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr

    def to_new_customer(self) -> Customer:
        return Customer.new(name=self.name, email=str(self.email))


class CustomerGet(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str

    @classmethod
    def from_model(cls, customer: Customer) -> Self:
        return cls.model_validate(customer)
